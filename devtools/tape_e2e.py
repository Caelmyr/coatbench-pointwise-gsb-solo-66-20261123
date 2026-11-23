"""End-to-end check for the tape-lift correspondence feature.

Builds a small synthetic specimen with pre-peel / post-peel / spread-tape
photos, runs a Surface observations (defects) measurement on the post-peel
frame, then exercises every tape-lift evidence rule and the observation ->
tape jump mapping.  Run with the project root on PYTHONPATH.
"""
import json
import sys

import numpy as np
from PIL import Image, ImageDraw

from coatbench.art import stored_preview
from coatbench.geometry import DEFAULT_CORNERS, canvas_dimensions
from coatbench.model import InputError
from coatbench.photos import png_bytes, store_capture
from coatbench.store import Store, make_id
from coatbench.tape import observation_locations, save_tape_lift, tape_overlay_image

WIDTH, HEIGHT = 640, 480


def panel_image(gap_centers, old_loss_center=None):
    """Coated coupon frame with dark exposed-metal gaps."""
    rng = np.random.default_rng(7)
    base = np.clip(
        np.dstack([
            np.full((HEIGHT, WIDTH), 0.30),
            np.full((HEIGHT, WIDTH), 0.42),
            np.full((HEIGHT, WIDTH), 0.38),
        ]) + rng.normal(0, 0.008, (HEIGHT, WIDTH, 3)),
        0, 1,
    )
    image = Image.fromarray(np.rint(base * 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    for cx, cy, rx, ry in gap_centers:
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(85, 62, 48))
    if old_loss_center:
        cx, cy, rx, ry = old_loss_center
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=(60, 45, 38), width=5)
        draw.ellipse((cx - rx + 7, cy - ry + 7, cx + rx - 7, cy + ry - 7), fill=(105, 80, 62))
    return image


def tape_image(piece_polygons, ruler_corners_a, ruler_corners_b):
    """Spread adhesive tape with film fragments and two ruler-note corner sets."""
    rng = np.random.default_rng(11)
    paper = np.clip(
        np.dstack([
            np.full((HEIGHT, WIDTH), 0.82),
            np.full((HEIGHT, WIDTH), 0.79),
            np.full((HEIGHT, WIDTH), 0.68),
        ]) + rng.normal(0, 0.01, (HEIGHT, WIDTH, 3)),
        0, 1,
    )
    image = Image.fromarray(np.rint(paper * 255).astype(np.uint8))
    draw = ImageDraw.Draw(image, "RGBA")
    # Tape strip outline.
    draw.rectangle((60, 60, WIDTH - 60, HEIGHT - 60), outline=(210, 205, 190), width=3)
    for polygon, color in piece_polygons:
        draw.polygon(polygon, fill=color, outline=(60, 80, 70))
    for corners, tone in ((ruler_corners_a, (40, 90, 160)), (ruler_corners_b, (160, 70, 40))):
        draw.line([*corners, corners[0]], fill=tone, width=2)
        for index, (x, y) in enumerate(corners, 1):
            draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill=tone)
            draw.text((x + 6, y - 6), f"{'A' if tone[2] > tone[0] else 'B'}{index}", fill=tone)
    return image


def photo(store, image, role, name):
    return store_capture(store.blobs, png_bytes(image), role, name, "synthetic check", make_id(), synthetic=True)


def normalized(points):
    return [[round(x / WIDTH, 5), round(y / HEIGHT, 5)] for x, y in points]


def main():
    store = Store("/tmp/tape-e2e-data")
    # Gap centers in pixel space.
    gaps_px = [(200, 180, 26, 20), (430, 300, 30, 24), (300, 360, 16, 14)]
    old_px = (520, 120, 22, 18)
    before = panel_image(gaps_px[:1], old_loss_center=old_px)
    after = panel_image(gaps_px, old_loss_center=old_px)
    ruler_a = normalized([(70, 70), (570, 70), (570, 410), (70, 410)])
    ruler_b = normalized([(570, 410), (70, 410), (70, 70), (570, 70)])
    tape = tape_image(
        [
            (normalized([(150, 120), (240, 110), (250, 200), (160, 210)]), (78, 110, 96, 255)),
            (normalized([(380, 240), (470, 250), (460, 340), (370, 330)]), (78, 110, 96, 255)),
            (normalized([(260, 320), (330, 320), (330, 390), (260, 390)]), (120, 100, 70, 255)),
        ],
        [(round(x * WIDTH), round(y * HEIGHT)) for x, y in ruler_a],
        [(round(x * WIDTH), round(y * HEIGHT)) for x, y in ruler_b],
    )

    pre_photo = photo(store, before, "diffuse", "pre-peel.png")
    post_photo = photo(store, after, "diffuse", "post-peel.png")
    tape_photo = photo(store, tape, "reference", "spread-tape.png")
    corners = DEFAULT_CORNERS
    size = canvas_dimensions(post_photo, corners, 100, 75)
    tile = store.create_tile({
        "name": "Salt spray coupon S-17",
        "batch": "Rack S",
        "body": "Mild steel", "glaze": "Grey polyester", "firing": "Salt spray 480 h",
        "width_mm": 100, "height_mm": 75,
        "photos": [pre_photo, post_photo, tape_photo],
        "plane": {"photo_id": post_photo["id"], "corners": corners, "size": list(size)},
        "regions": [], "registrations": {},
    })
    tile_id = tile["id"]

    # Post-peel Surface observations run (dark polarity finds the bare gaps).
    from coatbench.analysis import evaluate
    result = evaluate(store, tile_id, {
        "kind": "defects",
        "options": {"sensitivity": 0.85, "spot_radius": 5, "polarity": "dark",
                    "minimum_area": 40, "maximum_area": 4000},
        "region_id": None, "photo_id": post_photo["id"], "apply_neutral": False,
    })
    keys = [obs["key"] for obs in result["metrics"]["observations"]]
    assert len(keys) >= 4, f"expected 3 gaps plus pre-existing loss, got {keys}"

    # Identify the pre-existing loss observation nearest the old-loss center.
    centers = {obs["key"]: obs["normalized_center"] for obs in result["metrics"]["observations"]}
    old_norm = (old_px[0] / WIDTH, old_px[1] / HEIGHT)
    old_key = min(centers, key=lambda k: (centers[k][0] - old_norm[0]) ** 2 + (centers[k][1] - old_norm[1]) ** 2)
    print("pre-existing loss key:", old_key)
    new_gap_keys = [key for key in keys if key != old_key]
    assert len(new_gap_keys) == 3, new_gap_keys
    whole_key, second_key, third_key = new_gap_keys
    print("new film-loss gap keys:", new_gap_keys)

    pieces_payload = [
        {"name": "F1", "kind": "whole", "outline": normalized([(150, 120), (240, 110), (250, 200), (160, 210)]), "note": "large lifted sheet"},
        {"name": "F2", "kind": "whole", "outline": normalized([(380, 240), (470, 250), (460, 340), (370, 330)]), "note": ""},
        {"name": "F3", "kind": "split", "outline": normalized([(260, 320), (330, 320), (330, 390), (260, 390)]), "note": "two ends, two gaps"},
        {"name": "F4", "kind": "edge", "outline": normalized([(90, 300), (130, 300), (130, 360), (90, 360)]), "note": "one end outside frame"},
    ]
    base_payload = {
        "tape_photo_id": tape_photo["id"],
        "peel_result_id": result["id"],
        "orientations": [
            {"code": "A", "label": "Note A · ruler top-left", "corners": ruler_a, "note": "scale along top edge"},
            {"code": "B", "label": "Note B · rotated 180", "corners": ruler_b, "note": "scale along bottom edge"},
        ],
        "adopted_orientation": "A",
        "existing_loss_keys": [old_key],
        "pieces": pieces_payload,
    }
    piece_ids = {}

    def save(extra_claims):
        payload = {**base_payload, "claims": extra_claims}
        record = save_tape_lift(store, tile_id, payload)
        piece_ids.clear()
        for piece in record["pieces"]:
            piece_ids[piece["name"]] = piece["id"]
        return record

    # First save assigns server-side piece IDs; all pieces start held for review.
    save([])

    # 1. A whole piece confirmed against one gap; split/edge pieces held for review.
    record = save([
        {"piece_id": piece_ids["F1"], "state": "confirmed", "observation_key": whole_key},
        {"piece_id": piece_ids["F2"], "state": "confirmed", "observation_key": second_key},
        {"piece_id": piece_ids["F3"], "state": "review", "observation_key": third_key, "end": "first",
         "note": "second end lands in another gap"},
        {"piece_id": piece_ids["F4"], "state": "review", "observation_key": None,
         "note": "matching end never photographed"},
    ])
    assert record["adopted_orientation"] == "A"
    assert record["summary"] == {"piece_count": 4, "confirmed": 2, "pending": 2,
                                 "whole": 2, "split": 1, "edge": 1}, record["summary"]
    assert record["review_reasons"][piece_ids["F3"]] == "split-two-gaps"
    assert record["review_reasons"][piece_ids["F4"]] == "end-not-photographed"
    print("rule 1 ok: whole claims confirmed, split/edge held with reasons")

    # 2. One gap cannot take two whole pieces.
    try:
        save([
            {"piece_id": piece_ids["F1"], "state": "confirmed", "observation_key": whole_key},
            {"piece_id": piece_ids["F2"], "state": "confirmed", "observation_key": whole_key},
        ])
        raise AssertionError("duplicate gap claim should have failed")
    except InputError as exc:
        assert "already claimed" in str(exc), str(exc)
        print("rule 2 ok: duplicate gap claim rejected ->", exc)

    # 3. A split/edge piece cannot be force-confirmed.
    for name in ("F3", "F4"):
        try:
            save([{"piece_id": piece_ids[name], "state": "confirmed", "observation_key": third_key}])
            raise AssertionError("non-whole confirmation should have failed")
        except InputError as exc:
            assert "only a whole single-gap piece" in str(exc), str(exc)
    print("rule 3 ok: split/edge pieces cannot be confirmed")

    # 4. Pre-existing paint loss cannot be claimed as lifted film.
    try:
        save([{"piece_id": piece_ids["F1"], "state": "confirmed", "observation_key": old_key}])
        raise AssertionError("old loss claim should have failed")
    except InputError as exc:
        assert "pre-existing paint loss" in str(exc), str(exc)
        print("rule 4 ok: old paint loss protected ->", exc)

    # 5. Unknown observation key is rejected.
    try:
        save([{"piece_id": piece_ids["F1"], "state": "confirmed", "observation_key": "Z999"}])
        raise AssertionError("unknown key should have failed")
    except InputError as exc:
        assert "not in the post-peel" in str(exc), str(exc)
        print("rule 5 ok: unknown gap key rejected ->", exc)

    # 6. Orientation must be one of the two notes; bad corners rejected.
    bad = {**base_payload, "adopted_orientation": "C", "claims": []}
    try:
        save_tape_lift(store, tile_id, bad)
        raise AssertionError("bad orientation should have failed")
    except InputError as exc:
        assert "Adopted orientation" in str(exc), str(exc)
    bad_corners = {
        **base_payload,
        "orientations": [
            {"code": "A", "label": "A", "corners": ruler_a, "note": ""},
            {"code": "B", "label": "B", "corners": [[0.1, 0.5], [0.3, 0.5], [0.5, 0.5], [0.7, 0.5]], "note": ""},
        ],
        "claims": [],
    }
    try:
        save_tape_lift(store, tile_id, bad_corners)
        raise AssertionError("collinear ruler quad should have failed")
    except InputError as exc:
        assert "transform" in str(exc) or "perspective" in str(exc), str(exc)
        print("rule 6 ok: orientation and corner validation enforced ->", exc)

    # 7. Observation -> tape jump mapping under adopted orientation A.
    record = save([
        {"piece_id": piece_ids["F1"], "state": "confirmed", "observation_key": whole_key},
        {"piece_id": piece_ids["F2"], "state": "confirmed", "observation_key": second_key},
        {"piece_id": piece_ids["F3"], "state": "review", "observation_key": third_key, "end": "first"},
    ])
    locations = observation_locations(store, tile_id, result["id"])
    assert locations is not None and locations["adopted_orientation"] == "A"
    by_key = {entry["observation_key"]: entry for entry in locations["entries"]}
    f1 = by_key[whole_key]
    assert f1["claimed"] and f1["state"] == "confirmed" and f1["piece_names"] == ["F1"]
    f3 = by_key[third_key]
    assert f3["state"] == "review" and f3["reason"] == "split-two-gaps"
    assert by_key[old_key]["pre_existing"] is True
    # Ruler A maps the unit plane into the central tape region of the photo.
    from coatbench.geometry import homography
    panel_x, panel_y = centers[whole_key]
    matrix_a = homography(DEFAULT_CORNERS, ruler_a)
    expected_x = matrix_a[0, 0] * panel_x + matrix_a[0, 1] * panel_y + matrix_a[0, 2]
    expected_y = matrix_a[1, 0] * panel_x + matrix_a[1, 1] * panel_y + matrix_a[1, 2]
    tape_x, tape_y = f1["tape_point"]
    assert abs(tape_x - expected_x) < 0.005 and abs(tape_y - expected_y) < 0.005, \
        (tape_x, tape_y, expected_x, expected_y)
    print("rule 7 ok: jump mapping, pending reason, pre-existing flag all present")

    # 8. Overlay render works for full map and single highlight.
    full = tape_overlay_image(store, tile_id, result["id"])
    focused = tape_overlay_image(store, tile_id, result["id"], whole_key)
    assert full.size == focused.size
    digest = stored_preview(focused, store.blobs)
    assert store.blobs.require(digest).is_file()
    print("rule 8 ok: tape overlay renders (size %s, digest %s...)" % (full.size, digest[:10]))

    # 9. Switching adopted orientation to B remaps the jump points.
    payload_b = {**base_payload, "adopted_orientation": "B", "claims": [
        {"piece_id": piece_ids["F1"], "state": "confirmed", "observation_key": whole_key},
    ]}
    save_tape_lift(store, tile_id, payload_b)
    locations_b = observation_locations(store, tile_id, result["id"])
    assert locations_b["adopted_orientation"] == "B"
    point_b = next(e for e in locations_b["entries"] if e["observation_key"] == whole_key)["tape_point"]
    # B is the 180-degree rotated note: it maps (x, y) as if the unit plane
    # were flipped before applying note A.
    matrix_b = homography(DEFAULT_CORNERS, ruler_b)
    expected_bx = matrix_b[0, 0] * panel_x + matrix_b[0, 1] * panel_y + matrix_b[0, 2]
    expected_by = matrix_b[1, 0] * panel_x + matrix_b[1, 1] * panel_y + matrix_b[1, 2]
    assert abs(point_b[0] - expected_bx) < 0.005 and abs(point_b[1] - expected_by) < 0.005, point_b
    assert abs(point_b[0] - tape_x) > 0.05 or abs(point_b[1] - tape_y) > 0.05, (point_b, (tape_x, tape_y))
    print("rule 9 ok: adopted orientation B remaps jump target to", point_b)

    # 10. Persisted record reloads and decisions on the defects run still work.
    reloaded = store.tape_lift(tile_id)
    assert reloaded["adopted_orientation"] == "B" and reloaded["summary"]["piece_count"] == 4
    from coatbench.review import save_reviews
    updated = save_reviews(store, result["id"], result["version"],
                           {whole_key: {"decision": "confirm", "notes": "kept during tape work"}})
    assert updated["decisions"][whole_key]["decision"] == "confirm"
    print("rule 10 ok: tape record persisted; original confirm/dismiss review still works")

    print("\nALL TAPE-LIFT CHECKS PASSED")
    print(json.dumps({"tile_id": tile_id, "result_id": result["id"],
                      "tape_photo_id": tape_photo["id"], "old_key": old_key,
                      "observation_keys": keys}, indent=2))


if __name__ == "__main__":
    sys.exit(main())
