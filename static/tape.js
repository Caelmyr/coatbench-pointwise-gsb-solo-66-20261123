// Tape-lift correspondence workbench.
// Keeps the adopted tape orientation, outlines traced around the actual film
// pieces on the spread tape, and their one-to-one claims against post-peel
// Surface observations.  Whole pieces can only confirm one gap; split pieces
// and edge fragments stay "Held for check".
import {api, badge, btn, e, img, option, q, textField, areaField} from "./widgets.js";

const REASON_LABELS = {
  "split-two-gaps": "Two ends land in two gaps",
  "split-unresolved": "Split piece, gaps not resolved",
  "end-not-photographed": "Matching end was never photographed",
  "no-panel-match": "No panel gap matched yet",
  "held-for-check": "Held for check",
};

let dialog = null;
let drawPoints = [];
let drawLimit = 40;
let drawToken = 0;
let modalApi = null;

export function bindTape(deps) {
  dialog = deps.dialog;
  modalApi = deps.modal;
}

export async function loadTape(tileId) {
  const res = await api(`/api/specimens/${tileId}/tape-lift`);
  return res.record || null;
}

export function tapeTab(state) {
  const record = state.tapeRecord;
  const tapePhotos = state.tile.photos.filter(item => item.role === "reference");
  const peelRuns = state.results.filter(item => item.kind === "defects");
  if (!record) {
    return `<section class="card stack">
      <div class="title-row"><h3>Tape-lift correspondence</h3>${badge("Not started", "caution")}</div>
      <p class="soft">Choose the spread-tape photo and the post-peel Surface observations run, mark the two
        ruler-note orientations from the tape box, adopt one, then trace each lifted film piece along its
        photographed outline.</p>
      <div class="actions">${btn("Open tape workbench", "tape-open", "primary", "tape")}</div>
      ${tapePhotos.length ? "" : "<p class='notice warn'>Import the spread-tape photo with the Reference capture role first.</p>"}
      ${peelRuns.length ? "" : "<p class='notice warn'>Save a post-peel Surface observations measurement first.</p>"}
    </section>`;
  }
  const photo = state.tile.photos.find(item => item.id === record.tape_photo_id);
  const claims = new Map(record.claims.map(item => [item.piece_id, item]));
  const rows = record.pieces.map(piece => {
    const claim = claims.get(piece.id) || {};
    const confirmed = claim.state === "confirmed";
    const reason = record.review_reasons?.[piece.id];
    return `<div class="row">
      <div class="grow"><strong class="row-title">${e(piece.name)}</strong>
        <small>${e(piece.kind)} · ${piece.outline.length} outline points ·
        ${confirmed ? `confirmed → ${e(claim.observation_key)}` : `held for check${reason ? ` · ${e(REASON_LABELS[reason] || reason)}` : ""}`}
        </small></div>
      ${badge(confirmed ? "Confirmed" : "Held", confirmed ? "ready" : "caution")}
      ${btn("Edit", "tape-tab-edit", "tiny secondary", null, `data-id="${e(piece.id)}"`)}
    </div>`;
  }).join("");
  return `<div class="grid-detail">
    <section class="card stack">
      <div class="title-row"><h3>Spread tape · adopted orientation ${e(record.adopted_orientation)}</h3>
        ${badge(`${record.summary.confirmed} confirmed · ${record.summary.pending} held`, "caution")}</div>
      <figure class="stage">${img(`/api/specimens/${state.tile.id}/photos/${record.tape_photo_id}/preview`, "Spread tape with traced film pieces")}</figure>
      <p class="stage-foot">Ruler corners of both direction notes are stored; orientation
        <strong>${e(record.adopted_orientation)}</strong> is the adopted correspondence.</p>
      <div class="actions">${btn("Open tape workbench", "tape-open", "secondary", "tape")}
        ${btn("Show correspondence overlay", "tape-overlay", "secondary", "plot")}</div>
      <div id="tape-overlay-slot"></div>
    </section>
    <div class="stack">
      <section class="card"><h3>Film pieces (${record.summary.piece_count})</h3>
        <div class="divider-list scroll-list">${rows || "<p class='soft'>No pieces traced yet.</p>"}</div>
        <div class="actions">${btn("Trace another piece", "tape-piece-add", "tiny secondary", "plus")}</div>
      </section>
      <section class="card"><h3>Evidence rules</h3>
        <ul class="soft">
          <li>A whole piece confirms to exactly one post-peel gap.</li>
          <li>Split pieces spanning two gaps stay held for check.</li>
          <li>Edge fragments with an unphotographed end stay held.</li>
          <li>Pre-existing paint loss can never receive a claim.</li>
        </ul>
      </section>
    </div></div>`;
}

function photoChoices(state, selected) {
  const refs = state.tile.photos.filter(item => item.role === "reference");
  const pool = refs.length ? refs : state.tile.photos;
  return `<option value="">Choose spread-tape photo</option>` +
    pool.map(item => option(item.id, `${item.role_label} · ${item.name}`, selected)).join("");
}

function runChoices(state, selected) {
  const runs = state.results.filter(item => item.kind === "defects");
  return `<option value="">Choose post-peel Surface observations run</option>` +
    runs.map(item => option(item.id, `${item.label} · ${item.created_at.slice(0, 10)}`, selected)).join("");
}

function orientationBlock(code, label, corners, note) {
  return `<fieldset class="card tape-orientation" data-code="${code}">
    <legend class="micro">Direction note ${code}</legend>
    ${textField(`Orientation ${code} label`, `label-${code}`, label, 'maxlength="120"')}
    <p class="soft">Mark the four ruler corners clockwise (upper-left first) so the corner scale lines line up.</p>
    <div class="actions">${btn(`Mark note ${code} ruler corners`, "tape-ruler", "tiny secondary", "frame", `data-code="${code}"`)}
      <span class="soft" id="ruler-count-${code}">${corners.length ? corners.length + " points marked" : "not marked"}</span></div>
    ${areaField(`Orientation ${code} note`, `note-${code}`, note || "", 400)}
  </fieldset>`;
}

function workbenchHtml(state, draft) {
  const rec = draft.record;
  const photo = state.tile.photos.find(item => item.id === rec.tape_photo_id);
  const keys = draft.runKeys || [];
  const oldLoss = new Set(rec.existing_loss_keys || []);
  const claimRows = draft.pieces.map(piece => {
    const claim = draft.claims.find(item => item.piece_id === piece.id) || {state: "review", observation_key: "", end: "", note: ""};
    const gapOptions = [`<option value="">No panel gap (hold)</option>`]
      .concat(keys.map(key => {
        const flag = oldLoss.has(key) ? " · pre-existing loss" : "";
        return option(key, key + flag, claim.observation_key || "");
      })).join("");
    const stateChoice = ["review", "confirmed"].map(value =>
      option(value, value === "confirmed" ? "confirmed" : "held for check", claim.state)).join("");
    return `<tr>
      <td>${e(piece.name)}<br><small>${e(piece.kind)}</small></td>
      <td><select name="claim-state-${piece.id}">${stateChoice}</select></td>
      <td><select name="claim-key-${piece.id}">${gapOptions}</select></td>
      <td><select name="claim-end-${piece.id}">
        <option value="">any end</option>
        ${["first", "second"].map(value => option(value, value + " end", claim.end || "")).join("")}
      </select></td>
      <td><button type="button" class="button tiny ghost" data-do="tape-piece-edit" data-id="${e(piece.id)}">Outline</button></td>
    </tr>`;
  }).join("");
  const oldLossOptions = keys.map(key =>
    `<label class="field check"><input type="checkbox" name="oldloss" value="${e(key)}"${oldLoss.has(key) ? " checked" : ""}> ${e(key)}</label>`).join("");
  return `<div id="tape-form" class="form-stack">
    <div class="dialog-error" role="alert"></div>
    <div class="form-columns">
      <select id="field-tape_photo_id" name="tape_photo_id">${photoChoices(state, rec.tape_photo_id)}</select>
      <select id="field-peel_result_id" name="peel_result_id">${runChoices(state, rec.peel_result_id)}</select>
    </div>
    ${photo ? `<figure class="stage">${img(photo.preview_url, "Spread tape to trace")}</figure>` : ""}
    <div class="form-columns">
      ${orientationBlock("A", rec.orientations[0]?.label || "Note A", rec.orientations[0]?.corners || [], rec.orientations[0]?.note || "")}
      ${orientationBlock("B", rec.orientations[1]?.label || "Note B", rec.orientations[1]?.corners || [], rec.orientations[1]?.note || "")}
    </div>
    <div class="field"><label for="field-adopted">Adopted tape orientation</label>
      <select id="field-adopted" name="adopted_orientation">
        ${["A", "B"].map(code => option(code, `Adopt note ${code}`, rec.adopted_orientation)).join("")}
      </select></div>
    <section class="card"><h3>Traced film pieces</h3>
      <div class="table-wrap"><table><thead><tr><th>Piece</th><th>Disposition</th><th>Panel gap</th><th>Traced end</th><th>Outline</th></tr></thead>
        <tbody>${claimRows || `<tr><td colspan="5" class="soft">No pieces yet.</td></tr>`}</tbody></table></div>
      <div class="actions">${btn("Trace a film piece", "tape-piece-add", "tiny secondary", "plus")}</div>
    </section>
    <details><summary>Pre-existing paint loss (never claim these as lifted film)</summary>
      <div class="form-columns">${oldLossOptions || "<p class='soft'>Choose a post-peel run to list its observations.</p>"}</div></details>
    <div class="actions dialog-controls">
      <button type="button" class="button primary" data-do="tape-save">Save tape correspondence</button>
    </div>
  </div>`;
}

function defaultOrientations() {
  return [
    { code: "A", label: "Note A", corners: [], note: "" },
    { code: "B", label: "Note B", corners: [], note: "" },
  ];
}

function emptyDraft(state, record) {
  if (record) {
    const orientations = record.orientations?.length === 2 ? record.orientations : defaultOrientations();
    return {
      record: JSON.parse(JSON.stringify({
        tape_photo_id: record.tape_photo_id,
        peel_result_id: record.peel_result_id,
        orientations,
        adopted_orientation: record.adopted_orientation || "A",
        existing_loss_keys: record.existing_loss_keys || [],
      })),
      pieces: JSON.parse(JSON.stringify(record.pieces || [])),
      claims: JSON.parse(JSON.stringify((record.claims || []).map(({piece_id, state, observation_key, end, note}) =>
        ({piece_id, state, observation_key: observation_key || "", end: end || "", note: note || ""})))),
      runKeys: [],
    };
  }
  return {
    record: {
      tape_photo_id: state.tile.photos.find(item => item.role === "reference")?.id || "",
      peel_result_id: state.results.find(item => item.kind === "defects")?.id || null,
      orientations: defaultOrientations(),
      adopted_orientation: "A",
      existing_loss_keys: [],
    },
    pieces: [],
    claims: [],
    runKeys: [],
  };
}

async function fetchRunKeys(draft) {
  draft.runKeys = [];
  if (draft.record.peel_result_id) {
    const full = await api(`/api/results/${draft.record.peel_result_id}`);
    draft.runKeys = (full.metrics?.observations || []).map(item => item.key);
  }
}

export async function openWorkbench(state, focusPieceId = null) {
  const draft = state.tapeDraft && dialog.open ? state.tapeDraft : emptyDraft(state, state.tapeRecord);
  state.tapeDraft = draft;
  const renderWorkbench = () => {
    const content = workbenchHtml(state, draft);
    if (!dialog.open) {
      modalApi("Tape-lift correspondence", content, null, null, true);
    } else {
      const head = dialog.querySelector(".dialog-head");
      dialog.querySelectorAll("#tape-form").forEach(node => node.remove());
      head.insertAdjacentHTML("afterend", content);
    }
    bindWorkbenchEvents(state, draft, renderWorkbench);
  };
  await fetchRunKeys(draft);
  renderWorkbench();
  if (focusPieceId) {
    const piece = draft.pieces.find(item => item.id === focusPieceId);
    if (piece) tracePiece(state, draft, piece, renderWorkbench);
  }
}

function bindWorkbenchEvents(state, draft, rerender) {
  // Live-sync simple inputs into the draft.
  dialog.querySelectorAll("input[name^='label-'],textarea[name^='note-']").forEach(input => {
    input.addEventListener("change", () => {
      const [field, code] = input.name.split("-");
      const orientation = draft.record.orientations.find(item => item.code === code);
      if (orientation) orientation[field] = input.value;
    });
  });
  dialog.querySelector("#field-adopted")?.addEventListener("change", event => {
    draft.record.adopted_orientation = event.target.value;
  });
  dialog.querySelector("#field-tape_photo_id")?.addEventListener("change", event => {
    draft.record.tape_photo_id = event.target.value;
    rerender();
  });
  dialog.querySelector("#field-peel_result_id")?.addEventListener("change", async event => {
    draft.record.peel_result_id = event.target.value || null;
    await fetchRunKeys(draft);
    rerender();
  });
}

export async function handleSave(state) {
  const draft = state.tapeDraft;
  if (!draft) return;
  const root = dialog.querySelector("#tape-form");
  if (!root) return;
  const errorBox = root.querySelector(".dialog-error");
  try {
    await saveWorkbench(state, draft);
  } catch (err) {
    if (errorBox) errorBox.textContent = err.message;
  }
}

async function saveWorkbench(state, draft) {
  const root = dialog.querySelector("#tape-form");
  const tapePhotoId = root.querySelector("#field-tape_photo_id").value;
  const peelResultId = root.querySelector("#field-peel_result_id").value || null;
  if (!tapePhotoId) throw Error("Choose the spread-tape photo.");
  if (draft.record.orientations.some(item => item.corners.length !== 4)) {
    throw Error("Mark all four ruler corners for both direction notes.");
  }
  const claims = draft.pieces.map(piece => {
    const stateValue = root.querySelector(`[name="claim-state-${piece.id}"]`)?.value || "review";
    const observationKey = root.querySelector(`[name="claim-key-${piece.id}"]`)?.value || null;
    const end = root.querySelector(`[name="claim-end-${piece.id}"]`)?.value || null;
    return {
      piece_id: piece.id,
      state: stateValue,
      observation_key: observationKey,
      end,
      note: draft.claims.find(item => item.piece_id === piece.id)?.note || "",
    };
  });
  const existingLossKeys = Array.from(root.querySelectorAll("input[name='oldloss']:checked")).map(node => node.value);
  const payload = {
    tape_photo_id: tapePhotoId,
    peel_result_id: peelResultId,
    orientations: draft.record.orientations,
    adopted_orientation: root.querySelector("#field-adopted").value,
    existing_loss_keys: existingLossKeys,
    pieces: draft.pieces.map(({name, kind, outline, note}) => ({name, kind, outline, note})),
    claims,
  };
  const saved = await api(`/api/specimens/${state.tile.id}/tape-lift`, {method: "PUT", body: payload});
  state.tapeRecord = saved.record;
  state.tapeDraft = null;
  dialog.close();
  state.rerender();
}

function tracePiece(state, draft, piece, rerender) {
  const photo = state.tile.photos.find(item => item.id === draft.record.tape_photo_id);
  if (!photo) throw Error("Choose the spread-tape photo before tracing a piece.");
  const token = ++drawToken;
  modalApi(piece ? `Trace outline · ${piece.name}` : "Trace a lifted film piece", `
    <p class="notice">Click around the photographed film edge in order. At least three points close the outline.
      Whole pieces claim one gap; split pieces and edge fragments are held for check.</p>
    <div class="capture-drawing" id="tape-draw-stage"><img src="${e(photo.preview_url)}" alt="Spread tape for tracing">
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true" id="tape-draw-overlay"></svg></div>
    <div class="actions">
      <button type="button" class="button tiny secondary" data-do="tape-draw-clear">Clear points</button>
      <button type="button" class="button tiny ghost" data-do="tape-draw-undo">Undo point</button>
      <span class="soft" id="tape-draw-count"></span>
    </div>
    <div class="form-columns">
      ${textField("Piece label", "piece-name", piece?.name || `F${draft.pieces.length + 1}`, 'required maxlength="40"')}
      <select id="piece-kind" name="piece-kind">
        ${["whole", "split", "edge"].map(kind => option(kind, {whole: "whole · one gap", split: "split · two gaps", edge: "edge · end missing"}[kind], piece?.kind || "whole")).join("")}
      </select>
    </div>
    ${areaField("Piece note", "piece-note", piece?.note || "", 240)}
  `, "Save outline", async formData => {
    if (drawPoints.length < 3) throw Error("Mark at least three points to close the outline.");
    const name = formData.get("piece-name");
    if (draft.pieces.some(item => item.name === name && item.id !== piece?.id)) {
      throw Error("Piece labels must be unique.");
    }
    const entry = {
      id: piece?.id || crypto.randomUUID().replaceAll("-", "").slice(0, 24),
      name,
      kind: formData.get("piece-kind"),
      outline: drawPoints.map(([x, y]) => [Number(x.toFixed(6)), Number(y.toFixed(6))]),
      note: formData.get("piece-note") || "",
    };
    if (piece) {
      const index = draft.pieces.findIndex(item => item.id === piece.id);
      draft.pieces[index] = entry;
    } else {
      draft.pieces.push(entry);
      draft.claims.push({piece_id: entry.id, state: "review", observation_key: "", end: "", note: ""});
    }
    rerender();
  }, true);
  drawPoints = piece ? piece.outline.map(point => [...point]) : [];
  drawLimit = 60;
  paintTracing();
  const stage = q("#tape-draw-stage", dialog);
  const onClick = event => {
    if (token !== drawToken || event.target.closest("button")) return;
    const rect = stage.getBoundingClientRect();
    const u = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const v = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    if (drawPoints.length < drawLimit) {
      drawPoints.push([Number(u.toFixed(6)), Number(v.toFixed(6))]);
      paintTracing();
    }
  };
  stage.addEventListener("click", onClick);
  dialog.querySelectorAll("[data-do='tape-draw-clear']").forEach(button =>
    button.addEventListener("click", () => { drawPoints = []; paintTracing(); }));
  dialog.querySelectorAll("[data-do='tape-draw-undo']").forEach(button =>
    button.addEventListener("click", () => { drawPoints.pop(); paintTracing(); }));
}

function paintTracing() {
  const artist = q("#tape-draw-overlay", dialog);
  if (!artist) return;
  const coords = drawPoints.map(([x, y]) => [x * 1000, y * 1000]);
  const edge = coords.length < 3 ? "polyline" : "polygon";
  artist.innerHTML = `<${edge} class="draw-line" points="${coords.map(pair => pair.join(",")).join(" ")}"></${edge}>
    ${coords.map(([x, y], index) => `<circle class="draw-point" cx="${x}" cy="${y}" r="10"/>
      <text class="draw-label" x="${x + 16}" y="${y + 16}">${index + 1}</text>`).join("")}`;
  const count = q("#tape-draw-count", dialog);
  if (count) count.textContent = `${drawPoints.length} of ${drawLimit} points`;
}

function rulerMarking(state, draft, code, rerender) {
  const photo = state.tile.photos.find(item => item.id === draft.record.tape_photo_id);
  if (!photo) throw Error("Choose the spread-tape photo first.");
  const orientation = draft.record.orientations.find(item => item.code === code);
  const token = ++drawToken;
  modalApi(`Direction note ${code} · ruler corners`, `
    <p class="notice">Mark the four ruler scale corners clockwise, upper-left first. These align the corner
      scale lines between the tape box note and the spread tape.</p>
    <div class="capture-drawing" id="tape-draw-stage"><img src="${e(photo.preview_url)}" alt="Spread tape ruler marking">
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true" id="tape-draw-overlay"></svg></div>
    <div class="actions">
      <button type="button" class="button tiny secondary" data-do="tape-draw-clear">Clear points</button>
      <button type="button" class="button tiny ghost" data-do="tape-draw-undo">Undo point</button>
      <span class="soft" id="tape-draw-count"></span>
    </div>`, "Use these four corners", async () => {
    if (drawPoints.length !== 4) throw Error("Mark exactly four ruler corners.");
    orientation.corners = drawPoints.map(([x, y]) => [Number(x.toFixed(6)), Number(y.toFixed(6))]);
    rerender();
  }, true);
  drawPoints = orientation.corners.map(point => [...point]);
  drawLimit = 4;
  paintTracing();
  const stage = q("#tape-draw-stage", dialog);
  stage.addEventListener("click", event => {
    if (token !== drawToken || event.target.closest("button")) return;
    const rect = stage.getBoundingClientRect();
    const u = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const v = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    if (drawPoints.length < 4) {
      drawPoints.push([Number(u.toFixed(6)), Number(v.toFixed(6))]);
      paintTracing();
    }
  });
  dialog.querySelectorAll("[data-do='tape-draw-clear']").forEach(button =>
    button.addEventListener("click", () => { drawPoints = []; paintTracing(); }));
  dialog.querySelectorAll("[data-do='tape-draw-undo']").forEach(button =>
    button.addEventListener("click", () => { drawPoints.pop(); paintTracing(); }));
}

export function tapeAction(name, target, state) {
  const draft = state.tapeDraft;
  const rerender = () => openWorkbench(state);
  if (name === "tape-open") {
    void openWorkbench(state);
    return true;
  }
  if (name === "tape-tab-edit") {
    const pieceId = target.dataset.id;
    void openWorkbench(state, pieceId);
    return true;
  }
  if (name === "tape-piece-add") {
    if (draft) tracePiece(state, draft, null, rerender);
    return true;
  }
  if (name === "tape-piece-edit") {
    const piece = draft?.pieces.find(item => item.id === target.dataset.id);
    if (piece) tracePiece(state, draft, piece, rerender);
    return true;
  }
  if (name === "tape-ruler") {
    if (draft) rulerMarking(state, draft, target.dataset.code, rerender);
    return true;
  }
  if (name === "tape-overlay") {
    const record = state.tapeRecord;
    if (!record?.peel_result_id) return true;
    const slot = q("#tape-overlay-slot");
    if (slot) {
      slot.innerHTML = `<figure class="stage">
        ${img(`/api/results/${record.peel_result_id}/tape-map/overlay.png?v=${Date.now()}`, "Tape correspondence overlay")}</figure>
        <p class="stage-foot">Green = confirmed whole-piece claim · orange ? = held for check · grey = pre-existing loss.</p>`;
    }
    return true;
  }
  if (name === "tape-save") {
    void handleSave(state);
    return true;
  }
  return false;
}

export function jumpToTape(state, marker) {
  const record = state.tapeRecord;
  if (!record) {
    modalApi("Tape correspondence", "<p class='soft'>No tape-lift record exists for this specimen yet. Open the Tape lift tab to start one.</p>", null);
    return;
  }
  const locations = state.tapeMap;
  const entry = locations?.entries.find(item => item.observation_key === marker);
  if (!entry) {
    modalApi(`Tape position · ${marker}`, "<p class='soft'>This observation is not linked to the adopted tape orientation.</p>", null);
    return;
  }
  const photo = state.tile.photos.find(item => item.id === locations.tape_photo_id);
  const [x, y] = entry.tape_point;
  const left = `${(x * 100).toFixed(2)}%`;
  const top = `${(y * 100).toFixed(2)}%`;
  const status = entry.pre_existing ? "Pre-existing paint loss"
    : entry.state === "confirmed" ? `Confirmed · ${entry.piece_names.join(", ") || "matched piece"}`
    : `Held for check${entry.reason ? ` · ${REASON_LABELS[entry.reason] || entry.reason}` : ""}`;
  modalApi(`Tape original · ${marker}`, `
    <p class="notice">Adopted orientation ${e(locations.adopted_orientation)} · ${e(status)}</p>
    <div class="capture-drawing tape-jump" id="tape-jump-stage">
      ${img(photo.preview_url, `Original spread tape position of ${marker}`)}
      <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">
        <line x1="${(x * 1000 - 28).toFixed(1)}" y1="${(y * 1000).toFixed(1)}" x2="${(x * 1000 + 28).toFixed(1)}" y2="${(y * 1000).toFixed(1)}" class="tape-cross"/>
        <line x1="${(x * 1000).toFixed(1)}" y1="${(y * 1000 - 28).toFixed(1)}" x2="${(x * 1000).toFixed(1)}" y2="${(y * 1000 + 28).toFixed(1)}" class="tape-cross"/>
        <circle cx="${(x * 1000).toFixed(1)}" cy="${(y * 1000).toFixed(1)}" r="16" class="tape-cross-ring"/>
      </svg>
    </div>
    <p class="stage-foot">Crosshair at normalized tape position (${left}, ${top}) under the adopted ruler-note orientation.</p>`,
  null, null, true);
}
