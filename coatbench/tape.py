"""Tape-lift correspondence.

After a salt-spray coupon is peeled, the lifted film fragments remain on the
adhesive tape.  A tape-lift record keeps the adopted tape orientation (one of
the two direction notes shipped in the tape box), outlines traced from the
actual film pieces on the spread tape, and their correspondence to exposed
film-loss gaps on the post-peel panel.

A whole fragment can only be claimed against one panel gap.  Fragments whose
two ends land in two gaps, or whose matching end was never photographed, stay
in the pending "review" state instead of receiving a forced match.  Old paint
loss that was already present before peeling is never treated as a lifted
piece: only gaps backed by an observation in the post-peel Surface
observations measurement can receive a claim.
"""
from dataclasses import dataclass

import numpy as np
from PIL import ImageDraw

from .art import ACCENT, INK, SHADOW, font, load_artifact_picture, stored_preview
from .geometry import homography
from .model import (
    InputError,
    collection,
    dictionary,
    enumeration,
    identity,
    numeric_pair,
    string,
)
from .store import make_id

ORIENTATIONS = ("A", "B")
PIECE_KINDS = ("whole", "split", "edge")
CLAIM_STATES = ("confirmed", "review")
MAX_POINTS = 60
MAX_PIECES = 120
PREVIEW_MAX = 1440

CONFIRMED_COLOR = (162, 225, 171)
REVIEW_COLOR = ACCENT
ANCHOR_COLOR = (150, 196, 238)
EXISTING_LOSS_COLOR = (159, 162, 154)


@dataclass(frozen=True)
class Orientation:
    code: str
    label: str
    corners: list
    note: str


def parse_orientations(payload):
    """Read the two direction notes found in the tape box."""
    data = dictionary(payload, "Tape orientations")
    raw = collection(data.get("orientations"), "Tape orientation notes", minimum=2, maximum=2)
    seen = set()
    result = []
    for line in raw:
        item = dictionary(line, "Tape orientation note")
        code = enumeration(item.get("code"), ORIENTATIONS, "Orientation code")
        if code in seen:
            raise InputError("The two direction notes must carry different codes (A and B).")
        seen.add(code)
        corners = [
            numeric_pair(point, "Ruler corner", lower=0, upper=1)
            for point in collection(item.get("corners"), "Ruler corners", minimum=4, maximum=4)
        ]
        # A homography is computed now so an unusable direction note is rejected
        # before either orientation can be adopted.
        homography([[0, 0], [1, 0], [1, 1], [0, 1]], corners)
        result.append(Orientation(
            code=code,
            label=string(item.get("label"), f"Orientation {code} label", maximum=120),
            corners=corners,
            note=string(item.get("note"), f"Orientation {code} note", maximum=400, required=False),
        ))
    result.sort(key=lambda entry: entry.code)
    return [entry.__dict__ for entry in result]


def parse_polygon(value, label):
    points = [
        numeric_pair(point, f"{label} point", lower=0, upper=1)
        for point in collection(value, f"{label} outline", minimum=3, maximum=MAX_POINTS)
    ]
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += point[0] * nxt[1] - nxt[0] * point[1]
    if abs(area) < 0.000002:
        raise InputError(f"{label} outline is too small or degenerate.")
    return [[round(x, 6), round(y, 6)] for x, y in points]


def parse_pieces(payload, previous=()):
    raw = collection(payload.get("pieces"), "Tape film pieces", minimum=0, maximum=MAX_PIECES)
    prior = {piece["name"]: piece["id"] for piece in previous}
    pieces = []
    names = set()
    for line in raw:
        item = dictionary(line, "Tape film piece")
        name = string(item.get("name"), "Film piece label", maximum=40)
        key = name.casefold()
        if key in names:
            raise InputError("Film piece labels must be unique.")
        names.add(key)
        kind = enumeration(item.get("kind", "whole"), PIECE_KINDS, "Film piece kind")
        outline = parse_polygon(item.get("outline"), "Film piece")
        note = string(item.get("note"), "Film piece note", maximum=240, required=False)
        pieces.append({
            "id": prior.get(name, make_id()),
            "name": name,
            "kind": kind,
            "outline": outline,
            "note": note,
        })
    return pieces


def parse_claims(payload):
    raw = collection(payload.get("claims"), "Film claims", minimum=0, maximum=MAX_PIECES * 2)
    claims = []
    seen_pieces = set()
    for line in raw:
        item = dictionary(line, "Film claim")
        piece_id = identity(item.get("piece_id"), "Film piece ID")
        if piece_id in seen_pieces:
            raise InputError("List each film piece at most once in a save.")
        seen_pieces.add(piece_id)
        state = enumeration(item.get("state", "review"), CLAIM_STATES, "Claim state")
        observation_key = item.get("observation_key")
        if observation_key is not None:
            observation_key = string(observation_key, "Panel gap observation ID", maximum=8)
        end = item.get("end")
        if end is not None:
            end = enumeration(end, ("first", "second"), "Tracable fragment end")
        note = string(item.get("note"), "Claim note", maximum=240, required=False)
        claims.append({
            "piece_id": piece_id,
            "state": state,
            "observation_key": observation_key,
            "end": end,
            "note": note,
        })
    return claims


def panel_candidates(store, result_id):
    """Observations of the post-peel defects run, keyed for gap matching."""
    if not result_id:
        return None, None
    record = store.result(result_id)
    if record["kind"] != "defects":
        raise InputError("Choose a Surface observations measurement for the peeled panel.")
    return record, {entry["key"]: entry for entry in record["metrics"]["observations"]}


def validate_against_panels(pieces, claims, candidates, existing_loss_keys):
    """Apply the evidence rules and derive each piece's review state.

    Rules:
      * confirmed: one whole piece traced back to exactly one panel gap.
      * split/edge pieces, two-gap pieces, or pieces with an unphotographed
        end stay in review with a machine-readable reason.
      * only observations present in the post-peel run can receive a claim;
        pre-existing paint loss keys are rejected.
    """
    by_id = {piece["id"]: piece for piece in pieces}
    resolved = []
    claimed_gaps = {}
    for claim in claims:
        piece = by_id.get(claim["piece_id"])
        if piece is None:
            raise InputError("A claim references a film piece that is not part of this tape record.")
        key = claim["observation_key"]
        if claim["state"] == "confirmed":
            if not key:
                raise InputError(f"Confirmed piece {piece['name']} needs a panel gap observation.")
            if candidates is None or key not in candidates:
                raise InputError(f"Piece {piece['name']}: panel gap {key or '?'} is not in the post-peel Surface observations run.")
            if key in existing_loss_keys:
                raise InputError(
                    f"Piece {piece['name']}: {key} is pre-existing paint loss and cannot be claimed as lifted film.",
                )
            if piece["kind"] != "whole":
                raise InputError(
                    f"Piece {piece['name']} is marked {piece['kind']}; only a whole single-gap piece can be confirmed.",
                )
            if key in claimed_gaps:
                raise InputError(
                    f"Panel gap {key} is already claimed by {claimed_gaps[key]}; one gap takes one whole film piece.",
                )
            claimed_gaps[key] = piece["name"]
        elif key and candidates is not None and key not in candidates and key not in existing_loss_keys:
            raise InputError(f"Piece {piece['name']}: panel gap {key} is not in the post-peel Surface observations run.")
        elif key and key in existing_loss_keys:
            raise InputError(
                f"Piece {piece['name']}: {key} is pre-existing paint loss and cannot be claimed as lifted film.",
            )
        resolved.append(claim)
    # Pieces without an explicit claim row stay open for review.
    known = {entry["piece_id"] for entry in resolved}
    for piece in pieces:
        if piece["id"] not in known:
            resolved.append({
                "piece_id": piece["id"], "state": "review",
                "observation_key": None, "end": None, "note": "",
            })

    reasons = {}
    for claim in resolved:
        piece = by_id[claim["piece_id"]]
        if claim["state"] == "confirmed":
            continue
        if piece["kind"] == "split":
            reason = "split-two-gaps" if claim["observation_key"] else "split-unresolved"
        elif piece["kind"] == "edge":
            reason = "end-not-photographed"
        elif not claim["observation_key"]:
            reason = "no-panel-match"
        else:
            reason = "held-for-check"
        reasons[claim["piece_id"]] = reason
    return resolved, reasons


def build_tape_record(store, tile_id, payload):
    tile = store.tile(tile_id)
    data = dictionary(payload, "Tape-lift record")
    tape_photo_id = identity(data.get("tape_photo_id"), "Spread tape photo ID")
    tape_photo = next((item for item in tile["photos"] if item["id"] == tape_photo_id), None)
    if tape_photo is None:
        raise InputError("The spread-tape photo must be one of this specimen's captures.")
    peel_result_id = identity(data.get("peel_result_id"), "Post-peel measurement ID") if data.get("peel_result_id") else None
    peel_record, candidates = panel_candidates(store, peel_result_id)
    existing_loss = collection(
        data.get("existing_loss_keys", []), "Pre-existing paint loss keys", minimum=0, maximum=160,
    )
    existing_loss = [string(key, "Pre-existing paint loss key", maximum=8) for key in existing_loss]
    if candidates is not None:
        unknown = [key for key in existing_loss if key not in candidates]
        if unknown:
            raise InputError(f"Pre-existing loss key(s) not found in the post-peel run: {', '.join(unknown)}.")
    orientations = parse_orientations(data)
    adopted = enumeration(data.get("adopted_orientation"), ORIENTATIONS, "Adopted orientation")
    previous = store.tape_lift(tile_id)
    pieces = parse_pieces(data, previous["pieces"] if previous else ())
    claims = parse_claims(data)
    resolved, reasons = validate_against_panels(pieces, claims, candidates, set(existing_loss))

    confirmed = sum(1 for entry in resolved if entry["state"] == "confirmed")
    pending = len(resolved) - confirmed
    record = {
        "tile_id": tile_id,
        "tape_photo_id": tape_photo_id,
        "peel_result_id": peel_result_id,
        "orientations": orientations,
        "adopted_orientation": adopted,
        "existing_loss_keys": existing_loss,
        "pieces": pieces,
        "claims": resolved,
        "review_reasons": reasons,
        "summary": {
            "piece_count": len(pieces),
            "confirmed": confirmed,
            "pending": pending,
            "whole": sum(1 for piece in pieces if piece["kind"] == "whole"),
            "split": sum(1 for piece in pieces if piece["kind"] == "split"),
            "edge": sum(1 for piece in pieces if piece["kind"] == "edge"),
        },
    }
    record["preview_digest"] = render_tape_preview(store, record, peel_record)
    return record


def save_tape_lift(store, tile_id, payload):
    record = build_tape_record(store, tile_id, payload)
    return store.save_tape_lift(record)


def piece_fill(kind):
    if kind == "whole":
        return 96, 150, 116
    if kind == "split":
        return 178, 126, 74
    return 120, 132, 150


def render_tape_preview(store, record, peel_record):
    tape_photo_id = record["tape_photo_id"]
    tile = store.tile(record["tile_id"])
    photo = next(item for item in tile["photos"] if item["id"] == tape_photo_id)
    image = load_artifact_picture(store.blobs, photo["preview_digest"]).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    line = max(1, round(min(width, height) / 320))
    typeface = font(max(10, min(17, round(min(width, height) / 46))))
    claim_by_piece = {entry["piece_id"]: entry for entry in record["claims"]}

    adopted = next(item for item in record["orientations"] if item["code"] == record["adopted_orientation"])
    ruler = [(round(x * width), round(y * height)) for x, y in adopted["corners"]]
    draw.line([*ruler, ruler[0]], fill=(255, 255, 255, 210), width=line + 2, joint="curve")
    draw.line([*ruler, ruler[0]], fill=(*ANCHOR_COLOR, 230), width=line, joint="curve")
    for index, (x, y) in enumerate(ruler, 1):
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=ANCHOR_COLOR, outline=SHADOW, width=1)
        draw.text((x + 5, y - 14), f"{adopted['code']}{index}", font=typeface, fill=INK,
                  stroke_width=2, stroke_fill=SHADOW)

    for piece in record["pieces"]:
        claim = claim_by_piece.get(piece["id"], {"state": "review"})
        tone = CONFIRMED_COLOR if claim["state"] == "confirmed" else REVIEW_COLOR
        points = [(round(x * width), round(y * height)) for x, y in piece["outline"]]
        fill = (*piece_fill(piece["kind"]), 70)
        draw.polygon(points, fill=fill)
        draw.line([*points, points[0]], fill=SHADOW, width=line + 2, joint="curve")
        draw.line([*points, points[0]], fill=tone, width=line, joint="curve")
        anchor = points[0]
        label = piece["name"] if claim["state"] == "confirmed" else f"{piece['name']} ?"
        draw.text((anchor[0] + 4, anchor[1] - 14), label, font=typeface, fill=tone,
                  stroke_width=2, stroke_fill=SHADOW)

    banner = f"Tape orientation {adopted['code']} adopted · {record['summary']['confirmed']} confirmed · {record['summary']['pending']} held"
    draw.rounded_rectangle((10, 8, 12 + round(draw.textlength(banner, font=typeface)) + 12, 34),
                           radius=6, fill=(30, 38, 43, 215))
    draw.text((16, 12), banner, font=typeface, fill=INK)
    return stored_preview(image, store.blobs)


def refresh_preview(store, record):
    peel_record = store.result(record["peel_result_id"]) if record.get("peel_result_id") else None
    record["preview_digest"] = render_tape_preview(store, record, peel_record)
    return record


def observation_locations(store, tile_id, result_id):
    """Map each post-peel observation to its adopted-orientation tape spot."""
    tile = store.tile(tile_id)
    record = store.tape_lift(tile_id)
    if record is None:
        return None
    if record.get("peel_result_id") != result_id:
        return None
    defects = store.result(result_id)
    if defects["kind"] != "defects":
        raise InputError("This measurement has no spot observations.")
    adopted = next(item for item in record["orientations"] if item["code"] == record["adopted_orientation"])
    matrix = homography([[0, 0], [1, 0], [1, 1], [0, 1]], adopted["corners"])

    def to_tape(point):
        x, y = point
        denominator = matrix[2, 0] * x + matrix[2, 1] * y + matrix[2, 2]
        mapped_x = (matrix[0, 0] * x + matrix[0, 1] * y + matrix[0, 2]) / denominator
        mapped_y = (matrix[1, 0] * x + matrix[1, 1] * y + matrix[1, 2]) / denominator
        return [round(float(mapped_x), 6), round(float(mapped_y), 6)]

    claims = {}
    for claim in record["claims"]:
        if claim.get("observation_key"):
            claims.setdefault(claim["observation_key"], []).append(claim)
    pieces_by_id = {piece["id"]: piece for piece in record["pieces"]}
    entries = []
    for observation in defects["metrics"]["observations"]:
        key = observation["key"]
        linked = claims.get(key, [])
        entries.append({
            "observation_key": key,
            "tape_point": to_tape(observation["normalized_center"]),
            "panel_center": observation["normalized_center"],
            "claimed": bool(linked),
            "state": linked[0]["state"] if linked else "review",
            "piece_ids": [entry["piece_id"] for entry in linked],
            "piece_names": [pieces_by_id[entry["piece_id"]]["name"] for entry in linked if entry["piece_id"] in pieces_by_id],
            "pre_existing": key in record.get("existing_loss_keys", []),
            "reason": record["review_reasons"].get(linked[0]["piece_id"]) if linked else None,
        })
    return {
        "tape_photo_id": record["tape_photo_id"],
        "adopted_orientation": record["adopted_orientation"],
        "entries": entries,
    }


def tape_overlay_image(store, tile_id, result_id, highlight_key=None):
    """Render the spread tape with every linked gap marker, optionally focused."""
    locations = observation_locations(store, tile_id, result_id)
    if locations is None:
        return None
    tile = store.tile(tile_id)
    photo = next(item for item in tile["photos"] if item["id"] == locations["tape_photo_id"])
    image = load_artifact_picture(store.blobs, photo["preview_digest"]).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    line = max(1, round(min(width, height) / 320))
    typeface = font(max(10, min(18, round(min(width, height) / 44))))
    radius = max(7, round(min(width, height) / 90))
    for entry in locations["entries"]:
        if entry["pre_existing"]:
            tone = EXISTING_LOSS_COLOR
        elif entry["state"] == "confirmed":
            tone = CONFIRMED_COLOR
        else:
            tone = REVIEW_COLOR
        x, y = entry["tape_point"]
        px, py = round(x * width), round(y * height)
        box = (px - radius, py - radius, px + radius, py + radius)
        draw.ellipse(box, outline=SHADOW, width=line + 2)
        draw.ellipse(box, outline=tone, width=line)
        if entry["state"] != "confirmed":
            draw.line((box[0], box[1], box[2], box[3]), fill=tone, width=line)
            draw.line((box[0], box[3], box[2], box[1]), fill=tone, width=line)
        label = entry["observation_key"]
        draw.text((px + radius + 4, py - 8), label, font=typeface, fill=tone,
                  stroke_width=2, stroke_fill=SHADOW)
    if highlight_key:
        entry = next((item for item in locations["entries"] if item["observation_key"] == highlight_key), None)
        if entry is not None:
            x, y = entry["tape_point"]
            px, py = round(x * width), round(y * height)
            big = radius + 9
            draw.ellipse((px - big, py - big, px + big, py + big), outline=(255, 245, 225), width=line + 2)
    return image
