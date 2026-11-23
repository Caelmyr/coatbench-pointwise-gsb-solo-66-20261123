"""Full HTTP workflow test against a running CoatBench server.

Simulates the browser: create specimen, multipart photo upload (pre-peel,
post-peel, spread tape), plane, Surface observations run, tape-lift save with
the rule checks, observation jump data, overlay PNG, and legacy review.
"""
import io
import json
import sys
import urllib.error
import urllib.request
import uuid

import numpy as np
from PIL import Image, ImageDraw

BASE = "http://127.0.0.1:19987"
WIDTH, HEIGHT = 640, 480


def request(method, path, payload=None, files=None):
    if files is not None:
        boundary = "----coatbench" + uuid.uuid4().hex
        body = io.BytesIO()
        for key, value in payload.items():
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
        for field, (filename, data, mime) in files.items():
            body.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n".encode())
            body.write(f"Content-Type: {mime}\r\n\r\n".encode())
            body.write(data)
            body.write(b"\r\n")
        body.write(f"--{boundary}--\r\n".encode())
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        raw = body.getvalue()
    elif payload is not None:
        raw = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
    else:
        raw, headers = None, {}
    req = urllib.request.Request(BASE + path, data=raw, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            return resp.status, (json.loads(content) if "json" in ctype else content)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode())


def panel_png(gap_centers, old=None):
    rng = np.random.default_rng(3)
    base = np.clip(np.dstack([
        np.full((HEIGHT, WIDTH), 0.30), np.full((HEIGHT, WIDTH), 0.42), np.full((HEIGHT, WIDTH), 0.38),
    ]) + rng.normal(0, 0.008, (HEIGHT, WIDTH, 3)), 0, 1)
    image = Image.fromarray(np.rint(base * 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    for cx, cy, rx, ry in gap_centers:
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=(85, 62, 48))
    if old:
        cx, cy, rx, ry = old
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=(60, 45, 38), width=5)
        draw.ellipse((cx - rx + 7, cy - ry + 7, cx + rx - 7, cy + ry - 7), fill=(105, 80, 62))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def tape_png():
    rng = np.random.default_rng(5)
    paper = np.clip(np.dstack([
        np.full((HEIGHT, WIDTH), 0.82), np.full((HEIGHT, WIDTH), 0.79), np.full((HEIGHT, WIDTH), 0.68),
    ]) + rng.normal(0, 0.01, (HEIGHT, WIDTH, 3)), 0, 1)
    image = Image.fromarray(np.rint(paper * 255).astype(np.uint8))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((60, 60, WIDTH - 60, HEIGHT - 60), outline=(210, 205, 190), width=3)
    draw.polygon([(150, 120), (240, 110), (250, 200), (160, 210)], fill=(78, 110, 96, 255), outline=(60, 80, 70))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def norm(points):
    return [[round(x / WIDTH, 5), round(y / HEIGHT, 5)] for x, y in points]


def main():
    status, tile = request("POST", "/api/specimens", {
        "name": "HTTP salt spray S-18", "batch": "Rack T", "body": "Mild steel",
        "glaze": "Grey polyester", "firing": "Salt spray 480 h",
        "width_mm": 100, "height_mm": 75,
    })
    assert status == 201, status
    tile_id = tile["id"]
    version = tile["version"]
    print("created specimen", tile_id)

    def upload(path_png, role, name):
        nonlocal version
        status, updated = request("POST", f"/api/specimens/{tile_id}/photos",
                                  {"version": version, "role": role, "note": "http test"},
                                  {"photo": (name, path_png, "image/png")})
        assert status == 201, (status, updated)
        version = updated["version"]
        return next(item for item in updated["photos"] if item["name"] == name)["id"]

    pre_id = upload(panel_png([(200, 180, 26, 20)], (520, 120, 22, 18)), "diffuse", "pre.png")
    post_id = upload(panel_png([(200, 180, 26, 20), (430, 300, 30, 24), (300, 360, 16, 14)],
                               (520, 120, 22, 18)), "diffuse", "post.png")
    tape_id = upload(tape_png(), "reference", "tape.png")
    print("uploaded photos", pre_id, post_id, tape_id)

    corners = [[0, 0], [1, 0], [1, 1], [0, 1]]
    status, tile = request("PUT", f"/api/specimens/{tile_id}/plane",
                           {"version": version, "photo_id": post_id, "corners": corners,
                            "reset_regions": False, "respect_scale": True})
    assert status == 200, (status, tile)
    version = tile["version"]

    status, result = request("POST", f"/api/specimens/{tile_id}/results", {
        "kind": "defects",
        "options": {"sensitivity": 0.85, "spot_radius": 5, "polarity": "dark",
                    "minimum_area": 40, "maximum_area": 4000},
        "region_id": None, "photo_id": post_id, "apply_neutral": False,
    })
    assert status == 201, (status, result)
    result_id = result["id"]
    keys = [item["key"] for item in result["metrics"]["observations"]]
    print("defects run", result_id, keys)
    assert len(keys) >= 4

    # Identify the pre-existing loss key (nearest the old-loss center).
    centers = {item["key"]: item["normalized_center"] for item in result["metrics"]["observations"]}
    old_xy = (520 / WIDTH, 120 / HEIGHT)
    old_key = min(centers, key=lambda k: (centers[k][0] - old_xy[0]) ** 2 + (centers[k][1] - old_xy[1]) ** 2)
    new_keys = [key for key in keys if key != old_key]
    print("old loss key:", old_key, "new gap keys:", new_keys)

    ruler_a = norm([(70, 70), (570, 70), (570, 410), (70, 410)])
    ruler_b = norm([(570, 410), (70, 410), (70, 70), (570, 70)])
    pieces = [
        {"name": "F1", "kind": "whole", "outline": norm([(150, 120), (240, 110), (250, 200), (160, 210)]), "note": "large sheet"},
        {"name": "F2", "kind": "split", "outline": norm([(260, 320), (330, 320), (330, 390), (260, 390)]), "note": "two gaps"},
    ]
    tape_payload = {
        "tape_photo_id": tape_id, "peel_result_id": result_id,
        "orientations": [
            {"code": "A", "label": "Note A", "corners": ruler_a, "note": "top ruler"},
            {"code": "B", "label": "Note B", "corners": ruler_b, "note": "rotated"},
        ],
        "adopted_orientation": "A",
        "existing_loss_keys": [old_key],
        "pieces": pieces,
        "claims": [
            {"piece_id": "WILL-REPLACE", "state": "confirmed", "observation_key": new_keys[0]},
        ],
    }
    # First save without claims to obtain server piece ids.
    tape_payload["claims"] = []
    status, saved = request("PUT", f"/api/specimens/{tile_id}/tape-lift", tape_payload)
    assert status == 200, (status, saved)
    piece_id_by_name = {piece["name"]: piece["id"] for piece in saved["record"]["pieces"]}
    print("initial tape save:", saved["record"]["summary"])

    tape_payload["claims"] = [
        {"piece_id": piece_id_by_name["F1"], "state": "confirmed", "observation_key": new_keys[0]},
        {"piece_id": piece_id_by_name["F2"], "state": "review", "observation_key": new_keys[1], "end": "first"},
    ]
    status, saved = request("PUT", f"/api/specimens/{tile_id}/tape-lift", tape_payload)
    assert status == 200, (status, saved)
    rec = saved["record"]
    assert rec["summary"]["confirmed"] == 1 and rec["summary"]["pending"] == 1, rec["summary"]
    assert rec["review_reasons"][piece_id_by_name["F2"]] == "split-two-gaps"
    print("rule claims persisted:", rec["summary"])

    # Rule violations over HTTP return 422 with clear messages.
    bad = json.loads(json.dumps(tape_payload))
    bad["claims"] = [{"piece_id": piece_id_by_name["F1"], "state": "confirmed", "observation_key": old_key}]
    status, body = request("PUT", f"/api/specimens/{tile_id}/tape-lift", bad)
    assert status == 422 and "pre-existing paint loss" in body["error"], (status, body)
    print("422 old-loss protection:", body["error"])

    bad = json.loads(json.dumps(tape_payload))
    bad["claims"] = [{"piece_id": piece_id_by_name["F2"], "state": "confirmed", "observation_key": new_keys[1]}]
    status, body = request("PUT", f"/api/specimens/{tile_id}/tape-lift", bad)
    assert status == 422 and "only a whole single-gap" in body["error"], (status, body)
    print("422 split cannot confirm:", body["error"])

    # Observation list carries the tape jump data.
    status, observations = request("GET", f"/api/results/{result_id}/observations")
    assert status == 200
    assert "tape_locations" in observations
    entry = next(item for item in observations["tape_locations"]["entries"] if item["observation_key"] == new_keys[0])
    assert entry["claimed"] and entry["state"] == "confirmed" and entry["piece_names"] == ["F1"]
    held = next(item for item in observations["tape_locations"]["entries"] if item["observation_key"] == new_keys[1])
    assert held["state"] == "review" and held["reason"] == "split-two-gaps"
    old_entry = next(item for item in observations["tape_locations"]["entries"] if item["observation_key"] == old_key)
    assert old_entry["pre_existing"] is True
    print("observation jump data:", entry["observation_key"], entry["tape_point"], "held reason:", held["reason"])

    # Full result document also carries the jump data for the saved view.
    status, full = request("GET", f"/api/results/{result_id}")
    assert full["tape_locations"]["adopted_orientation"] == "A"
    print("result document includes tape_locations")

    # Tape map overlay PNG renders.
    status, png = request("GET", f"/api/results/{result_id}/tape-map/overlay.png?observation={new_keys[0]}")
    assert status == 200 and isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n"
    print("overlay PNG bytes:", len(png))

    # Legacy confirm/dismiss review still works after the tape work.
    current = request("GET", f"/api/results/{result_id}")[1]["version"]
    status, reviewed = request("PUT", f"/api/results/{result_id}/observations/{new_keys[2]}",
                               {"version": current, "decision": "dismiss", "notes": "legacy flow"})
    assert status == 200 and reviewed["decisions"][new_keys[2]]["decision"] == "dismiss", (status, reviewed)
    print("legacy review intact, version", reviewed["version"])

    # No tape record on a fresh specimen gives an empty envelope, not an error.
    status, other = request("POST", "/api/specimens", {"name": "No tape yet", "width_mm": 10, "height_mm": 10})
    status, empty = request("GET", f"/api/specimens/{other['id']}/tape-lift")
    assert status == 200 and empty == {"items": [], "record": None}, (status, empty)
    print("empty tape-lift envelope ok")

    print("\nHTTP WORKFLOW TEST PASSED")


if __name__ == "__main__":
    sys.exit(main())
