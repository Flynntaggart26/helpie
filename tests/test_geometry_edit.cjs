"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const geometry = require("../ui/geometry-edit.js");

const sample = () => [{ kind: "geometry", objects: [
  { kind: "point", x: 0.2, y: 0.3, label: "A" },
  { kind: "segment", x1: 0.1, y1: 0.2, x2: 0.8, y2: 0.9, label: "L" },
  { kind: "circle", cx: 0.5, cy: 0.5, radius: 0.2, label: "C" },
  { kind: "polygon", points: [[0.1, 0.1], [0.7, 0.1], [0.4, 0.8]], label: "P" },
] }];

test("lists and resolves each editable handle", () => {
  const items = sample();
  const choices = geometry.handles(items);
  assert.equal(choices.length, 7);
  assert.deepEqual(choices.map(c => c.key), ["0:0:point", "0:1:start", "0:1:end", "0:2:center", "0:3:vertex0", "0:3:vertex1", "0:3:vertex2"]);
  assert.equal(geometry.resolve(items, "0:3:vertex2").y, 0.8);
  assert.equal(geometry.resolve(items, "0:1:vertex1"), null);
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
