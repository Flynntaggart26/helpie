"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const pdf = require("../ui/note-pdf.js");

test("generates a bounded PDF with accurate byte offsets and image bytes", async () => {
  const image = new Uint8Array([255, 216, 1, 2, 255, 217]);
  const bytes = Buffer.from(await pdf.build(image, 800, 400).arrayBuffer());
  const str = bytes.toString("latin1");
  assert.ok(str.startsWith("%PDF-1.4\n"));
  assert.ok(bytes.includes(Buffer.from(image)));
  const offset = Number(/startxref\n(\d+)/.exec(str)[1]);
  assert.equal(str.slice(offset, offset + 4), "xref");
  const lines = str.slice(offset).split("\n");
  for (let id = 1; id <= 5; id++) {
    const pos = Number(lines[id + 2].slice(0, 10));
    assert.equal(str.slice(pos, pos + 7), `${id} 0 obj`);
  }
  assert.throws(() => pdf.build(image, 0, 400));
});
