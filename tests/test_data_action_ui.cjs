"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

test("data actions confirm or cancel the same approval token", async () => {
  const source = fs.readFileSync("ui/app.js", "utf8");
  const start = source.indexOf("async function confirmDataAction(");
  const end = source.indexOf("async function loadMemory(", start);
  assert.ok(start >= 0 && end > start);
  for (const accepted of [true, false]) {
    const calls = [];
    const context = {
      window: {confirm: () => accepted},
      api: async (path, options) => {
        calls.push({path, body: JSON.parse(options.body)});
        return path.endsWith("prepare") ? {token: "test-token", preview: "Delete?"} : {confirmed: true};
      },
    };
    const action = vm.runInNewContext(`${source.slice(start, end)}; confirmDataAction`, context);
    await action("forget_memory", {text: "test"});
    assert.equal(calls[0].path, "/api/action-approval/prepare");
    assert.equal(calls[1].path, accepted ? "/api/action-approval/confirm" : "/api/action-approval/cancel");
    assert.equal(calls[1].body.token, "test-token");
  }
});
