"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const geometry = require("../ui/geometry-edit.js");

const sample = () => [{ kind: "geometry", x: 0.1, y: 0.2, width: 0.8, height: 0.6, objects: [
  { kind: "point", x: 0.2, y: 0.3, label: "A" },
  { kind: "segment", x1: 0.1, y1: 0.2, x2: 0.8, y2: 0.9, label: "L" },
  { kind: "circle", cx: 0.5, cy: 0.5, radius: 0.2, label: "C" },
  { kind: "polygon", points: [[0.1, 0.1], [0.7, 0.1], [0.4, 0.8]], label: "P" },
] }];

test("lists and resolves each editable handle", () => {
  const items = sample();
  const choices = geometry.handles(items);
  assert.equal(choices.length, 8);
  assert.deepEqual(choices.map(c => c.key), ["0:0:point", "0:1:start", "0:1:end", "0:2:center", "0:2:radius", "0:3:vertex0", "0:3:vertex1", "0:3:vertex2"]);
  assert.equal(geometry.resolve(items, "0:3:vertex2").y, 0.8);
  assert.equal(geometry.resolve(items, "0:1:vertex1"), null);
});

test("circle radius and center stay inside the geometry box", () => {
  const items = sample();
  const edit = geometry.propose(items, "0:2:center", 0.4, 0.5, "C", 0.3);
  assert.equal(edit.object.radius, 0.3);
  assert.equal(items[0].objects[2].radius, 0.2);
  assert.equal(geometry.propose(items, "0:2:center", 0.4, 0.5, "C", 0), null);
  assert.equal(geometry.propose(items, "0:2:center", 0.4, 0.5, "C", 0.6), null);
  assert.equal(geometry.propose(items, "0:2:radius", 0.5, 0.5, "C"), null);
  assert.ok(Math.abs(geometry.propose(items, "0:2:radius", 0.8, 0.5, "C").object.radius - 0.3) < 1e-9);
});

test("hit testing and coordinates respect geometry box and non-square canvas", () => {
  const items = sample();
  const p = geometry.canvasPosition(items, "0:0:point", 1000, 500);
  assert.ok(Math.abs(p.x - 260) < 1e-9);
  assert.ok(Math.abs(p.y - 190) < 1e-9);
  assert.equal(geometry.hitTest(items, 1000, 500, p.x + 2, p.y + 2), "0:0:point");
  assert.equal(geometry.hitTest(items, 1000, 500, 999, 499), null);
  const pos = geometry.localPosition(items, "0:0:point", 1000, 500, p.x, p.y);
  assert.ok(Math.abs(pos.x - 0.2) < 1e-9);
  assert.ok(Math.abs(pos.y - 0.3) < 1e-9);
  assert.equal(geometry.localPosition(items, "0:0:point", 0, 500, 1, 1), null);
});

test("valid edits are copies and preserve unrelated geometry", () => {
  const items = sample();
  const result = geometry.propose(items, "0:3:vertex1", 0.6, 0.4, "  triangle  ");
  assert.deepEqual(result.object.points[1], [0.6, 0.4]);
  assert.deepEqual(items[0].objects[3].points[1], [0.7, 0.1]);
  assert.equal(result.object.label, "triangle");
});

test("rejects out-of-bounds points, collapsed segments and escaped circles", () => {
  const items = sample();
  assert.equal(geometry.propose(items, "0:0:point", NaN, 0.4, ""), null);
  assert.equal(geometry.propose(items, "0:1:start", 0.8, 0.9, ""), null);
  assert.equal(geometry.propose(items, "0:2:center", 0.1, 0.5, ""), null);
  assert.equal(geometry.propose(items, "0:3:vertex7", 0.5, 0.5, ""), null);
});

test("drag cancellation, undo, save and reopen keep the correct geometry", async () => {
  const elements = {
    "visual-note-canvas": { getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 500 }), setPointerCapture() {} },
    "visual-point-select": { value: "" },
    "visual-note-status": { textContent: "" },
    "visual-note-title": { value: "Geometry", focus() {} },
  };
  const sandbox = {
    HelpieGeometry: geometry,
    document: { getElementById: id => elements[id] },
    window: { addEventListener() {}, confirm: () => true },
    items: sample(), JSON, Number, Math, URLSearchParams,
    setTimeout, clearTimeout,
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../ui/app.js"), "utf8"), sandbox);
  vm.runInContext(`
    drawVisualNoteCanvas = () => {};
    loadVisualPointEditor = () => {};
    loadVisualNotes = async () => {};
    state.visualNoteItems = items;
    let storedNote = null;
    api = async (url, options = {}) => {
      if (url === "/api/visual-notes/save") {
        const body = JSON.parse(options.body);
        storedNote = { id: "note-1", title: body.title, strokes: body.strokes, visual_items: body.visual_items };
        return { note: JSON.parse(JSON.stringify(storedNote)) };
      }
      if (url === "/api/visual-notes/note-1") return { note: JSON.parse(JSON.stringify(storedNote)) };
      throw new Error("unexpected endpoint");
    };
  `, sandbox);
  const run = code => vm.runInContext(code, sandbox);
  const down = `beginGeometryDrag({pointerType:"mouse", button:0, pointerId:7, clientX:260, clientY:190})`;
  const move = `continueGeometryDrag({pointerId:7, clientX:420, clientY:250})`;
  run(`${down}; ${move}; finishGeometryDrag({pointerId:7}, true)`);
  assert.equal(run("state.visualNoteItems[0].objects[0].x"), 0.2);
  assert.equal(run("state.visualNoteUndoStack.length"), 0);
  run(`${down}; ${move}; finishGeometryDrag({pointerId:7})`);
  assert.equal(run("state.visualNoteItems[0].objects[0].x"), 0.4);
  assert.equal(run("state.visualNoteUndoStack.length"), 1);
  run("undoVisualNote()");
  assert.equal(run("state.visualNoteItems[0].objects[0].x"), 0.2);
  run(`${down}; ${move}; finishGeometryDrag({pointerId:7})`);
  await run("saveVisualNote()");
  run("state.visualNoteItems = []; state.visualNoteDirty = false");
  await run('openVisualNote("note-1")');
  assert.equal(run("state.visualNoteItems[0].objects[0].x"), 0.4);
  assert.equal(run("state.visualNoteItems[0].objects[0].y"), 0.5);
  run('beginGeometryDrag({pointerType:"mouse", button:0, pointerId:8, clientX:660, clientY:250});'
    + 'continueGeometryDrag({pointerId:8, clientX:740, clientY:250}); finishGeometryDrag({pointerId:8})');
  assert.ok(Math.abs(run("state.visualNoteItems[0].objects[2].radius") - 0.3) < 1e-9);
  run("undoVisualNote()");
  assert.equal(run("state.visualNoteItems[0].objects[2].radius"), 0.2);
});
