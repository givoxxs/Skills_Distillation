import assert from "node:assert/strict";
import test from "node:test";

import { buildRunQuery, parseRunParams, parseRunQuery } from "./run-ui-state";

const SKILLS = ["docx", "internal-comms", "slack-gif-creator"] as const;

test("run query parser accepts selected skill", () => {
  assert.deepEqual(parseRunQuery("?skill=slack-gif-creator", SKILLS, "docx"), {
    skill: "slack-gif-creator",
  });
});

test("run params parser falls back for unknown skill", () => {
  assert.deepEqual(parseRunParams({ skill: "missing" }, SKILLS, "docx"), {
    skill: "docx",
  });
});

test("run query builder preserves current skill", () => {
  assert.equal(buildRunQuery({ skill: "internal-comms" }), "?skill=internal-comms");
});
