"use strict";
const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

test("window titles render as text and only after a click", async () => {
  const source = fs.readFileSync("ui/app.js", "utf8");
  const a = source.indexOf("function formatReviewPath(");
  const b = source.indexOf("async function loadRecycleHistory(", a);
  const start = source.indexOf('  $("window-review-start").addEventListener(');
  const end = source.indexOf('  let reviewRoot', start);
  assert.ok(a >= 0 && b > a && start >= 0 && end > start);
  let handler, calls = 0;
  const list = {items: [], replaceChildren() { this.items = []; }, appendChild(item) { this.items.push(item); }};
  const button = {disabled: false, addEventListener(_event, fn) {handler = fn;}};
  const status = {textContent: ""};
  const inspectResults = {replaceChildren() {}};
  const controls = {"window-review-start": button, "window-review-results": list, "window-review-status": status,
                    "window-inspect-results": inspectResults, "window-inspect-status": {textContent: ""}};
  const context = {
    $: id => controls[id],
    document: {createElement: () => ({textContent: "", dir: "", children: [], append(...items) {this.children.push(...items);}, setAttribute() {}, addEventListener() {}})},
    api: async () => {calls++; return {windows: [{title:"<img>\u202eexe", token:"test"}], limited: false};},
  };
  vm.runInNewContext(source.slice(a, b) + source.slice(start, end), context);
  assert.equal(calls, 0);
  await handler();
  assert.equal(calls, 1);
  assert.equal(list.items[0].children[0].textContent, "<img>\\u202eexe");
  assert.equal(list.items[0].dir, "ltr");
  assert.equal(button.disabled, false);
});
