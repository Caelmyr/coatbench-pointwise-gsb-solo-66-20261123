// DOM-level smoke test for the tape-lift frontend using jsdom.
// Run: node /workspace/devtools/tape_dom_test.mjs
import { JSDOM } from "jsdom";

const dom = new JSDOM(`<!DOCTYPE html><body><dialog id="dialog"></dialog><div id="main"></div></body>`);
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
const dialog = document.getElementById("dialog");
dialog.showModal = () => { dialog.open = true; };
dialog.close = () => { dialog.open = false; };

let modalCalls = [];
const modalStub = (title, html, submitLabel, onSubmit, wide) => {
  modalCalls.push({ title, html });
  dialog.open = true;
  dialog.innerHTML = `<div class="dialog-head"><h2>${title}</h2></div>${html}`;
  dialog._onSubmit = onSubmit;
};

const tape = await import("/workspace/static/tape.js");
tape.bindTape({ dialog, modal: modalStub });

const photo = { id: "tapephoto0000000000000001", role: "reference", role_label: "Reference capture",
  name: "tape.png", preview_url: "/tape-preview.png" };
const state = {
  tile: { id: "tile000000000000000000000001", photos: [photo] },
  results: [{ id: "result0000000000000000000001", kind: "defects", label: "Surface observations",
    created_at: "2026-11-23T10:00:00+00:00" }],
  tapeRecord: null,
  tapeMap: null,
  tapeDraft: null,
  rerender() {},
};

// 1. Empty state tab prompts to start. With a reference photo present and a
// defects run saved, neither prerequisite warning appears.
let html = tape.tapeTab(state);
if (!html.includes("Open tape workbench")) {
  throw new Error("empty-state tape tab failed");
}
if (html.includes("Reference capture role first") || html.includes("Surface observations measurement first")) {
  throw new Error("prerequisite warnings should not show when inputs already exist");
}
console.log("1 ok: empty tape tab renders start card");

// 2. Existing record tab summarizes pieces and evidence status.
state.tapeRecord = {
  tape_photo_id: photo.id, peel_result_id: state.results[0].id,
  adopted_orientation: "A",
  summary: { piece_count: 2, confirmed: 1, pending: 1, whole: 1, split: 1, edge: 0 },
  pieces: [
    { id: "p1", name: "F1", kind: "whole", outline: [[0.1, 0.1], [0.2, 0.1], [0.2, 0.2]] },
    { id: "p2", name: "F2", kind: "split", outline: [[0.3, 0.3], [0.4, 0.3], [0.4, 0.4]] },
  ],
  claims: [
    { piece_id: "p1", state: "confirmed", observation_key: "D002", end: null, note: "" },
    { piece_id: "p2", state: "review", observation_key: "D003", end: "first", note: "" },
  ],
  review_reasons: { p2: "split-two-gaps" },
};
html = tape.tapeTab(state);
for (const token of ["adopted orientation A", "F1", "confirmed → D002", "Two ends land in two gaps", "Confirmed", "Held"]) {
  if (!html.includes(token)) throw new Error(`record tab missing ${token}`);
}
console.log("2 ok: record tab shows confirmed and held pieces with reasons");

// 3. Workbench opens with both orientation notes and the piece claim table.
globalThis.fetch = async (url, init) => {
  if (String(url).endsWith("/api/results/result0000000000000000000001")) {
    return { ok: true, json: async () => ({ metrics: { observations: [
      { key: "D001" }, { key: "D002" }, { key: "D003" }, { key: "D004" },
    ] } }) };
  }
  throw new Error("unexpected fetch " + url);
};
await tape.openWorkbench(state);
const workbench = modalCalls.at(-1).html;
for (const token of ["Direction note A", "Direction note B", "Adopt note A", "Adopt note B",
  "tape-ruler", "F1", "F2", "Save tape correspondence", "D002", "Pre-existing paint loss", "Trace a film piece"]) {
  if (!workbench.includes(token)) throw new Error(`workbench missing ${token}`);
}
// Every observation key is offered both as a gap option and an old-loss checkbox.
for (const key of ["D001", "D002", "D003", "D004"]) {
  if (!workbench.includes(`name="oldloss" value="${key}"`)) throw new Error(`old-loss checkbox missing for ${key}`);
}
if (!workbench.includes('name="claim-state-p1"') || !workbench.includes('value="confirmed"')) {
  throw new Error("claim state controls missing");
}
console.log("3 ok: workbench renders both orientations, ruler buttons, claim table and old-loss checkboxes");

// 4. Ruler marking modal collects exactly four corner clicks.
const draft = state.tapeDraft;
tape.tapeAction("tape-ruler", { dataset: { code: "A" } }, state);
const rulerModal = modalCalls.at(-1);
if (!rulerModal.title.includes("Direction note A") || !rulerModal.html.includes("tape-draw-stage")) {
  throw new Error("ruler modal failed");
}
// Simulate four clicks on the drawing stage.
const stage = document.getElementById("tape-draw-stage");
const rect = { left: 0, top: 0, width: 100, height: 100 };
stage.getBoundingClientRect = () => rect;
for (const [cx, cy] of [[10, 10], [90, 10], [90, 90], [10, 90]]) {
  stage.dispatchEvent(new dom.window.MouseEvent("click", { clientX: cx, clientY: cy, bubbles: true }));
}
await dialog._onSubmit(new FormDataShim());
const savedCorners = draft.record.orientations.find(o => o.code === "A").corners;
if (savedCorners.length !== 4) throw new Error("ruler corners not saved: " + JSON.stringify(savedCorners));
console.log("4 ok: four ruler clicks stored on note A ->", JSON.stringify(savedCorners));

// Both direction notes must carry four ruler corners before a save is accepted.
tape.tapeAction("tape-ruler", { dataset: { code: "B" } }, state);
const rulerStageB = document.getElementById("tape-draw-stage");
rulerStageB.getBoundingClientRect = () => rect;
for (const [cx, cy] of [[88, 12], [12, 12], [12, 88], [88, 88]]) {
  rulerStageB.dispatchEvent(new dom.window.MouseEvent("click", { clientX: cx, clientY: cy, bubbles: true }));
}
await dialog._onSubmit(new FormDataShim());
if (draft.record.orientations.find(o => o.code === "B").corners.length !== 4) {
  throw new Error("note B ruler corners missing");
}
console.log("4b ok: note B ruler corners also stored");

// 5. Tracing a new piece opens the outline modal and stores the polygon.
tape.tapeAction("tape-piece-add", { dataset: {} }, state);
const traceModal = modalCalls.at(-1);
if (!traceModal.title.includes("Trace") || !traceModal.html.includes("piece-kind")) {
  throw new Error("trace modal failed");
}
const traceStage = document.getElementById("tape-draw-stage");
traceStage.getBoundingClientRect = () => rect;
for (const [cx, cy] of [[20, 20], [80, 25], [75, 80], [25, 75]]) {
  traceStage.dispatchEvent(new dom.window.MouseEvent("click", { clientX: cx, clientY: cy, bubbles: true }));
}
const beforeCount = draft.pieces.length;
await dialog._onSubmit(new FormDataShim({ "piece-name": "F3", "piece-kind": "edge", "piece-note": "end off frame" }));
if (draft.pieces.length !== beforeCount + 1) throw new Error("new piece not added");
const added = draft.pieces.at(-1);
if (added.name !== "F3" || added.kind !== "edge" || added.outline.length !== 4) {
  throw new Error("traced piece fields wrong: " + JSON.stringify(added));
}
const newClaim = draft.claims.find(c => c.piece_id === added.id);
if (!newClaim || newClaim.state !== "review") throw new Error("new piece must start held for check");
console.log("5 ok: traced edge piece F3 added with 4-point outline, held for check");

// 6. Save posts the full payload and adopts the record.
let posted = null;
globalThis.fetch = async (url, init = {}) => {
  if (String(url).includes("/tape-lift") && init.method === "PUT") {
    posted = JSON.parse(init.body);
    return { ok: true, json: async () => ({ record: { ...posted, id: "rec1", summary: { piece_count: 3 } } }) };
  }
  if (String(url).endsWith("/api/results/result0000000000000000000001")) {
    return { ok: true, json: async () => ({ metrics: { observations: [
      { key: "D001" }, { key: "D002" }, { key: "D003" }, { key: "D004" },
    ] } }) };
  }
  throw new Error("unexpected fetch " + url);
};
// The workbench DOM was replaced by the trace dialog; rerender it so #tape-form exists,
// then trigger the same global action dispatch main.js performs.
await tape.openWorkbench(state);
tape.tapeAction("tape-save", { dataset: {} }, state);
await new Promise(resolve => setTimeout(resolve, 0));
if (!posted) throw new Error("save did not PUT");
for (const token of ["tape_photo_id", "peel_result_id", "orientations", "adopted_orientation", "pieces", "claims"]) {
  if (!(token in posted)) throw new Error("payload missing " + token);
}
if (posted.orientations.length !== 2 || posted.orientations[0].corners.length !== 4) {
  throw new Error("payload orientations wrong");
}
if (state.tapeRecord.adopted_orientation !== posted.adopted_orientation) throw new Error("record not adopted after save");
console.log("6 ok: save PUTs orientations, pieces and claims; record adopted");

// 7. Defects detail renders tape jump button and held marker; jump modal shows crosshair.
const results = await import("/workspace/static/results.js");
const record = {
  kind: "defects",
  decisions: { D002: { decision: "confirm" } },
  metrics: { observations: [
    { key: "D002", type: "spot", area_pixels: 120, polarity: "dark" },
    { key: "D003", type: "spot", area_pixels: 88, polarity: "dark" },
  ] },
  tape_locations: { adopted_orientation: "A", tape_photo_id: photo.id, entries: [
    { observation_key: "D002", state: "confirmed", claimed: true, piece_names: ["F1"],
      tape_point: [0.42, 0.38], pre_existing: false },
    { observation_key: "D003", state: "review", claimed: true, reason: "split-two-gaps",
      tape_point: [0.61, 0.71], pre_existing: false },
  ] },
};
const detail = results.defectsDetail(record, record.tape_locations);
if (!detail.includes("defect-tape-jump") || !detail.includes('data-marker="D003"')) {
  throw new Error("tape jump buttons missing in defects detail");
}
if (!detail.includes("held for check") || !detail.includes("tape confirmed")) {
  throw new Error("held/confirmed status text missing");
}
console.log("7 ok: defects rows show tape jump button and held-for-check status");

state.tapeMap = record.tape_locations;
tape.jumpToTape(state, "D003");
const jump = modalCalls.at(-1);
if (!jump.title.includes("D003") || !jump.html.includes("tape-cross") || !jump.html.includes("Held for check")) {
  throw new Error("jump modal missing crosshair or held status");
}
if (!jump.html.includes("/tape-preview.png")) throw new Error("jump modal must show the original tape photo");
console.log("8 ok: jump modal opens original tape photo with crosshair and held reason");

console.log("\nALL FRONTEND DOM CHECKS PASSED");

// Minimal FormData stand-in for modal submit callbacks.
function FormDataShim(values = {}) {
  const store = new Map(Object.entries({ "piece-name": "F3", "piece-kind": "whole", "piece-note": "", ...values }));
  return { get: key => (store.has(key) ? store.get(key) : null) };
}
