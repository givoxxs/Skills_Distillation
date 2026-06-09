import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCompareQuery,
  comparePhaseSteps,
  modeHelpText,
  normalizeCompareError,
  parseCompareParams,
  parseCompareQuery,
  scoreDeltaLabel,
} from "./compare-ui-state";

test("phase timeline marks completed and active live phases", () => {
  const steps = comparePhaseSteps("running");

  assert.deepEqual(
    steps.map((step) => [step.key, step.state]),
    [
      ["queued", "done"],
      ["running", "active"],
      ["judge", "pending"],
      ["done", "pending"],
    ],
  );
});

test("query parser and builder preserve demo state", () => {
  const parsed = parseCompareQuery(
    "?skill=slack-gif-creator&mode=live&case=tc_a03&prompt=custom&fixture=demo.txt",
    ["docx", "slack-gif-creator"],
    "docx",
  );

  assert.deepEqual(parsed, {
    skill: "slack-gif-creator",
    mode: "live",
    testCaseId: "tc_a03",
    promptMode: "custom",
    fixtureFile: "demo.txt",
  });

  assert.equal(
    buildCompareQuery(parsed),
    "?skill=slack-gif-creator&mode=live&case=tc_a03&prompt=custom&fixture=demo.txt",
  );
});

test("search params parser accepts Next server searchParams shape", () => {
  assert.deepEqual(
    parseCompareParams(
      {
        skill: "docx",
        mode: "replay",
        case: ["tc_c06"],
        prompt: "test_case",
      },
      ["docx", "slack-gif-creator"],
      "docx",
    ),
    {
      skill: "docx",
      mode: "replay",
      testCaseId: "tc_c06",
      promptMode: "test_case",
      fixtureFile: undefined,
    },
  );
});

test("mode and error copy exposes operational constraints", () => {
  assert.match(modeHelpText("replay"), /stored artifacts/i);
  assert.match(modeHelpText("live"), /OPENROUTER_API_KEY/);
  assert.match(
    normalizeCompareError("compare live -> 400 OPENROUTER_API_KEY is required"),
    /backend .env/i,
  );
});

test("score delta label summarizes winner margin", () => {
  assert.equal(scoreDeltaLabel({ winner: "peak", score_original: 0.534, score_peak: 0.96 }), "Peak +0.426");
  assert.equal(scoreDeltaLabel({ winner: "tie", score_original: 0.7, score_peak: 0.71 }), "Tie");
});
