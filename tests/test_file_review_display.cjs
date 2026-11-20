"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

test("file review makes direction controls and newlines visible", () => {
  const source = fs.readFileSync("ui/app.js", "utf8");
  const start = source.indexOf("function formatReviewPath(");
  const end = source.indexOf("async function loadRecycleHistory(", start);
  assert.ok(start >= 0 && end > start);
  const format = vm.runInNewContext(`${source.slice(start, end)}; formatReviewPath`);
  assert.equal(format("ödev\u202eexe.pdf\n"), "ödev\\u202eexe.pdf\\u000a");
  assert.equal(format("normal/ödev.pdf"), "normal/ödev.pdf");
});
