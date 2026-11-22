"""Bracket a panel reading between the steps of one photographed step card.

A review can carry a dark card and a light card in the same frame, but the batch
keeps one card family only.  Each step that was clearly photographed is sampled
with the same color basis as the panel patch.  A repeat capture can report a
color move only when the approval reading and the repeat reading both fall
between the *same pair of adjacent, clearly photographed steps*.  A step from
the other card, or a step that was not photographed on either occasion, is
never used to close a gap.
"""

from dataclasses import dataclass

import numpy as np
from PIL import ImageDraw

from .art import SHADOW, base_rgba, curve_points, font
from .color import float_list, lab_linear, linear_lab, swatch
from .geometry import analysis_mask, exclusion_mask, polygon_mask
from .model import InputError


MIN_STEP_SAMPLES = 24
MIN_STEP_SUPPORT_PERCENT = 82.0
MIN_PAIR_SEPARATION = 1.0
ON_STEP_TOLERANCE = 0.6

LEGAL_TONE = (126, 226, 168)
RESOLVED_TONE = (118, 192, 205)
PENDING_TONE = (238, 170, 92)
OUTSIDE_TONE = (146, 154, 158)
CARD_BG = (18, 28, 32)
CARD_TEXT = (238, 242, 224)


@dataclass(frozen=True)
class StepReading:
    number: int
    nominal: float
    captured: bool
    readable: bool
    reason: str | None
    lightness: float | None = None
    median_lab: list | None = None
    pixels: int = 0
    support_percent: float = 0.0
    swatch: str = "#000000"


def ordered_levels(card):
    return sorted(card["levels"], key=lambda item: item["number"])


def card_order(card):
    return {level["number"]: index for index, level in enumerate(ordered_levels(card))}


def patch_reading(frame, tile, linear, vertices):
    area = polygon_mask(frame.extent, vertices) & ~exclusion_mask(frame.extent, tile["regions"])
    requested = int(np.count_nonzero(area))
    if requested == 0:
        return None
    support = analysis_mask(frame, area, minimum=MIN_STEP_SAMPLES, allow_clipped=False)
    covered = 100.0 * np.count_nonzero(support) / requested
    center = np.median(linear_lab(linear[support]), axis=0)
    return {
        "median_lab": float_list(center, 5),
        "lightness": round(float(center[0]), 5),
        "pixels": int(np.count_nonzero(support)),
        "support_percent": round(float(covered), 2),
        "swatch": swatch(lab_linear(center)),
    }


def read_level(frame, tile, linear, level):
    """Read one step patch, keeping a readable/why-not state for the record."""
    if not level.get("captured", True):
        return StepReading(level["number"], level["nominal"], False, False, "not marked as clearly photographed")
    vertices = level.get("vertices")
    if not vertices:
        return StepReading(level["number"], level["nominal"], True, False, "no patch marked")
    try:
        data = patch_reading(frame, tile, linear, vertices)
    except InputError as error:
        return StepReading(level["number"], level["nominal"], True, False, str(error))
    if data is None or data["support_percent"] < MIN_STEP_SUPPORT_PERCENT:
        percent = 0.0 if data is None else data["support_percent"]
        return StepReading(
            level["number"], level["nominal"], True, False, "not clearly supported in this capture",
            pixels=0 if data is None else data["pixels"], support_percent=percent,
        )
    return StepReading(
        level["number"], level["nominal"], True, True, None,
        lightness=data["lightness"], median_lab=data["median_lab"], pixels=data["pixels"],
        support_percent=data["support_percent"], swatch=data["swatch"],
    )


def read_card(frame, tile, linear, card):
    return [read_level(frame, tile, linear, level) for level in ordered_levels(card)]


def resolved_runs(card, readings):
    """Contiguous runs of clearly photographed steps, in card order."""
    order = card_order(card)
    numbers = sorted((item.number for item in readings if item.readable), key=lambda number: order[number])
    runs = []
    for number in numbers:
        if runs and order[number] == order[runs[-1][-1]] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    lookup = {item.number: item for item in readings}
    levels = {level["number"]: level for level in card["levels"]}
    result = []
    for run in runs:
        result.append({
            "from": run[0],
            "to": run[-1],
            "steps": run,
            "nominal": [levels[run[0]]["nominal"], levels[run[-1]]["nominal"]],
            "lightness": [lookup[run[0]].lightness, lookup[run[-1]].lightness],
        })
    return result


def retained_range(card, readings):
    """What span of the card this capture can defend, and which ends stay open."""
    levels = ordered_levels(card)
    order = card_order(card)
    resolved = sorted((item for item in readings if item.readable), key=lambda item: order[item.number])
    runs = resolved_runs(card, readings)
    numbers = {item.number for item in resolved}
    darkest = levels[0]["number"]
    lightest = levels[-1]["number"]
    retained = {
        "runs": runs,
        "resolved_steps": [item.number for item in resolved],
        "darkest_step": darkest,
        "lightest_step": lightest,
        "dark_end_resolved": darkest in numbers,
        "light_end_resolved": lightest in numbers,
    }
    retained["note"] = range_note(retained)
    return retained


def range_note(retained):
    if not retained["runs"]:
        return "No step on this card was clearly photographed."
    spans = " · ".join(f"{run['from']}–{run['to']}" for run in retained["runs"])
    notes = [f"Defensible card span: steps {spans}."]
    if not retained["dark_end_resolved"]:
        notes.append(
            f"The darkest step ({retained['darkest_step']}) was not clearly photographed,"
            " so the dark end is unconfirmed."
        )
    if not retained["light_end_resolved"]:
        notes.append(
            f"The lightest step ({retained['lightest_step']}) was not clearly photographed,"
            " so the light end is unconfirmed."
        )
    return " ".join(notes)


def usable_pair(lower, upper, order):
    return (
        order[upper.number] == order[lower.number] + 1
        and upper.lightness - lower.lightness >= MIN_PAIR_SEPARATION
    )


def anchor(reading, readings, card):
    """Where a panel reading sits on the card ladder.

    Returns either ("step", step) when the reading is effectively on a
    photographed step, ("pair", (lower, upper)) when it is strictly inside an
    adjacent photographed pair, or None when neither holds. An on-step reading
    is not pushed into a neighbouring pair: that would let a repeat capture
    claim a same-pair comparison it did not really have.
    """
    order = card_order(card)
    ordered = sorted((item for item in readings if item.readable), key=lambda item: order[item.number])
    lightness = float(reading[0])
    for item in ordered:
        if abs(lightness - item.lightness) <= ON_STEP_TOLERANCE:
            return "step", item
    for lower, upper in zip(ordered, ordered[1:]):
        if not usable_pair(lower, upper, order):
            continue
        if lower.lightness < lightness < upper.lightness:
            return "pair", (lower, upper)
    return None


def fraction_between(value, lower, upper):
    span = upper - lower
    if abs(span) < 1e-6:
        return None
    return float((value - lower) / span)


def outside_note(reading, readings, card):
    order = card_order(card)
    ordered = sorted((item for item in readings if item.readable), key=lambda item: order[item.number])
    lightness = float(reading[0])
    if not ordered:
        return "no step is readable in this capture"
    if lightness < ordered[0].lightness:
        return f"darker than step {ordered[0].number}"
    if lightness > ordered[-1].lightness:
        return f"lighter than step {ordered[-1].number}"
    return "between steps that are not an adjacent photographed pair"


def basis_card(basis):
    return {
        "id": basis["card_id"],
        "kind": basis["card_kind"],
        "label": basis["card_label"],
        "levels": [
            {
                "number": item["number"],
                "nominal": item["nominal"],
                "captured": item["captured"],
                "vertices": item.get("vertices"),
            }
            for item in basis["levels"]
        ],
    }


def approval_readings(basis):
    return [
        StepReading(
            item["number"], item["nominal"], item["captured"], item["readable"], item.get("reason"),
            lightness=item["lightness"], median_lab=item["median_lab"], pixels=item["pixels"],
            support_percent=item["support_percent"], swatch=item["swatch"],
        )
        for item in basis["readings"]
    ]


def build_basis(frame, tile, linear, card):
    """Freeze the card readings and the defensible span at approval time."""
    readings = read_card(frame, tile, linear, card)
    if not any(item.readable for item in readings):
        raise InputError("None of the marked steps on this step card is clearly readable in this capture.")
    return {
        "card_id": card["id"],
        "card_kind": card["kind"],
        "card_label": card["label"],
        "photo_id": frame.photo["id"],
        "levels": [
            {
                "number": level["number"],
                "nominal": level["nominal"],
                "captured": level.get("captured", True),
                "vertices": level.get("vertices"),
            }
            for level in ordered_levels(card)
        ],
        "readings": [
            {
                "number": item.number,
                "nominal": item.nominal,
                "captured": item.captured,
                "readable": item.readable,
                "reason": item.reason,
                "median_lab": item.median_lab,
                "lightness": item.lightness,
                "pixels": item.pixels,
                "support_percent": item.support_percent,
                "swatch": item.swatch,
            }
            for item in readings
        ],
        "resolved_numbers": [item.number for item in readings if item.readable],
        "retained": retained_range(card, readings),
    }


def compare_against_basis(tile, frame, linear, basis, now_reading, before_reading):
    """Resample the frozen card and hold both panel readings on the same anchor."""
    card = basis_card(basis)
    previous = approval_readings(basis)
    current = read_card(frame, tile, linear, card)
    now_anchor = anchor(now_reading, current, card)
    before_anchor = anchor(before_reading, previous, card)
    result = {
        "card_id": basis["card_id"],
        "card_kind": basis["card_kind"],
        "card_label": basis["card_label"],
        "approved_span": basis["retained"],
        "current_span": retained_range(card, current),
        "approved_reading": float_list(np.asarray(before_reading), 5),
        "repeat_reading": float_list(np.asarray(now_reading), 5),
        "status": "pending",
        "legal": False,
        "reason": None,
        "anchor": None,
        "bracket": None,
        "fraction_before": None,
        "fraction_now": None,
        "fraction_shift": None,
        "pending_steps": [
            item.number for item in current if item.captured and not item.readable
        ],
        "unmarked_steps": [
            item.number for item in current if not item.captured
        ],
        "occluded_approved_steps": [
            item.number for item in previous
            if item.readable and not next(
                (now for now in current if now.number == item.number and now.readable), None
            )
        ],
        "current_steps": [
            {
                "number": item.number,
                "nominal": item.nominal,
                "captured": item.captured,
                "readable": item.readable,
                "median_lab": item.median_lab,
                "lightness": item.lightness,
                "swatch": item.swatch,
                "support_percent": item.support_percent,
                "reason": item.reason,
            }
            for item in current
        ],
    }
    result["anchor"] = anchor_label(before_anchor)
    if before_anchor is None:
        result["status"] = "unbracketed"
        result["reason"] = (
            "The approved reading was not held between two adjacent clearly photographed steps"
            f" ({outside_note(before_reading, previous, card)}), so this card basis cannot report a"
            " same-pair move."
        )
        return result
    if now_anchor is None:
        result["status"] = "pending"
        result["reason"] = (
            "The repeat reading is not held between two adjacent clearly photographed steps"
            f" ({outside_note(now_reading, current, card)}). Photograph the missing step."
        )
        return result
    if anchor_label(now_anchor) != anchor_label(before_anchor):
        if "step" in {before_anchor[0], now_anchor[0]}:
            result["status"] = "boundary"
            result["reason"] = (
                "The panel falls on a step boundary in one capture and between steps in the other"
                f" ({anchor_label(before_anchor)} before, {anchor_label(now_anchor)} now)."
                " A boundary reading is not treated as a between-step move; re-shoot to clear it."
            )
            return result
        result["status"] = "shifted"
        result["reason"] = (
            f"The panel sits on a different step position now ({anchor_label(before_anchor)} before,"
            f" {anchor_label(now_anchor)} now). That is not a same-anchor comparison."
        )
        return result
    if before_anchor[0] == "step":
        return finish_on_step(result, before_anchor[1], now_anchor[1])
    lower_before, upper_before = before_anchor[1]
    lower_now, upper_now = now_anchor[1]
    result["status"] = "bracketed"
    result["legal"] = True
    result["bracket"] = {
        "lower": lower_now.number,
        "upper": upper_now.number,
        "lower_nominal": lower_now.nominal,
        "upper_nominal": upper_now.nominal,
    }
    result["fraction_before"] = round(
        fraction_between(float(before_reading[0]), lower_before.lightness, upper_before.lightness), 5
    )
    result["fraction_now"] = round(
        fraction_between(float(now_reading[0]), lower_now.lightness, upper_now.lightness), 5
    )
    if result["fraction_before"] is not None and result["fraction_now"] is not None:
        result["fraction_shift"] = round(result["fraction_now"] - result["fraction_before"], 5)
    return result


def finish_on_step(result, before_step, now_step):
    result["status"] = "on-step"
    result["reason"] = (
        f"The panel sits on step {before_step.number} in both captures, not between two steps."
        " A same-step match supports no lighter or darker move."
    )
    result["bracket"] = None
    result["anchor"] = {"kind": "step", "step": before_step.number, "nominal": before_step.nominal}
    return result


def anchor_label(found):
    if found is None:
        return "outside the photographed steps"
    kind, value = found
    if kind == "step":
        return f"step {value.number}"
    lower, upper = value
    return f"steps {lower.number}–{upper.number}"


def overlay(frame, tile, basis, comparison, source=None):
    """Draw the card ladder: legal bracket, resolved steps, and steps still to shoot."""
    image = base_rgba(frame, source)
    draw = ImageDraw.Draw(image)
    width, height = image.size
    line = max(1, round(min(width, height) / 330))
    level_font = font(max(10, min(17, round(min(width, height) / 52))))
    legal = comparison.get("bracket")
    legal_numbers = {legal["lower"], legal["upper"]} if legal else set()
    current = {item["number"]: item for item in comparison["current_steps"]}
    short = min(width, height)
    for level in basis["levels"]:
        vertices = level.get("vertices")
        if not vertices:
            continue
        points = curve_points(vertices, image.size)
        reading = current.get(level["number"])
        if level["number"] in legal_numbers:
            tone = LEGAL_TONE
        elif reading and reading["readable"]:
            tone = RESOLVED_TONE
        elif reading is not None and reading.get("captured"):
            tone = PENDING_TONE
        else:
            tone = OUTSIDE_TONE
        draw.line([*points, points[0]], width=line + 2, fill=SHADOW, joint="curve")
        draw.line([*points, points[0]], width=line, fill=tone, joint="curve")
        if tone == PENDING_TONE:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
            span = max(8, round(short / 55))
            offset = left - (bottom - top)
            while offset < right:
                draw.line(
                    (max(left, offset), bottom, min(right, offset + (bottom - top)), top),
                    fill=PENDING_TONE, width=max(1, line),
                )
                offset += span
        x, y = points[0]
        draw.text((x + 4, y + 3), str(level["number"]), fill=CARD_TEXT, stroke_width=2,
                  stroke_fill=SHADOW, font=level_font)

    strip_height = max(62, round(height * 0.145))
    strip = ImageDraw.Draw(image)
    strip.rectangle((0, height - strip_height, width, height), fill=CARD_BG)
    title_font = font(max(12, min(22, round(short / 40))))
    detail_font = font(max(10, min(16, round(short / 55))))
    margin = max(6, round(strip_height * 0.08))
    if comparison["legal"]:
        headline = (
            f"Legal comparison · steps {comparison['bracket']['lower']}–"
            f"{comparison['bracket']['upper']} · step-fraction shift {comparison['fraction_shift']:+0.3f}"
        )
        tone = LEGAL_TONE
    elif comparison["status"] == "shifted":
        headline = "Not a legal comparison · the step position changed between captures"
        tone = PENDING_TONE
    elif comparison["status"] == "boundary":
        headline = "Panel is on a step boundary in one capture · re-shoot to clear it"
        tone = PENDING_TONE
    elif comparison["status"] == "on-step":
        headline = "Panel rests on one step in both captures · no between-step move"
        tone = PENDING_TONE
    elif comparison["status"] == "pending":
        headline = "Awaiting a photographed step · no legal comparison yet"
        tone = PENDING_TONE
    else:
        headline = "No legal bracket from this card basis"
        tone = PENDING_TONE
    padding = max(10, round(width * 0.012))
    row = (strip_height - 2 * margin) / 3
    strip.text((padding, height - strip_height + margin), clipped_text(strip, headline, title_font, width - 2 * padding),
               fill=tone, font=title_font)
    spans = " · ".join(f"{run['from']}–{run['to']}" for run in comparison["approved_span"]["runs"]) or "none"
    pending = ", ".join(str(number) for number in comparison["pending_steps"]) or "none"
    unmarked = ", ".join(str(number) for number in comparison.get("unmarked_steps", [])) or "none"
    note = f"Approved span {spans} · to re-photograph: {pending} · not on card: {unmarked}"
    strip.text(
        (padding, height - strip_height + margin + row),
        clipped_text(strip, note, detail_font, width - 2 * padding),
        fill=CARD_TEXT,
        font=detail_font,
    )
    if comparison["legal"]:
        shift = comparison["fraction_shift"]
        direction = "lighter" if shift > 0.02 else "darker" if shift < -0.02 else "unchanged"
        legend = f"Same pair; panel is {direction} within the step span"
        legend_tone = LEGAL_TONE
    elif comparison.get("reason"):
        legend = comparison["reason"]
        legend_tone = PENDING_TONE
    else:
        legend = "Grey hatch: not photographed or not marked on the card"
        legend_tone = OUTSIDE_TONE
    strip.text(
        (padding, height - strip_height + margin + 2 * row),
        clipped_text(strip, legend, detail_font, width - 2 * padding),
        fill=legend_tone,
        font=detail_font,
    )
    return image


def clipped_text(draw, text, typeface, available):
    if draw.textlength(text, font=typeface) <= available:
        return text
    label = text
    while label and draw.textlength(label + "…", font=typeface) > available:
        label = label[:-1]
    return label + "…"
