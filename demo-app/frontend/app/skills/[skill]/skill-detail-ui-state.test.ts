import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSkillDetailQuery,
  parseSkillDetailParams,
  parseSkillDetailQuery,
} from "./skill-detail-ui-state";

const OPTIONS = {
  diffRounds: [0, 1, 2, 3, 4, 5],
  evalRounds: [1, 2, 3, 4, 5],
  workflows: ["create", "edit"],
  fallbackFrom: 0,
  fallbackTo: 5,
  fallbackEvalRound: 5,
};

test("skill detail query parser preserves shareable view state", () => {
  assert.deepEqual(
    parseSkillDetailQuery(
      "?from=1&to=4&round=3&workflow=edit&sort=rule_score&dir=asc&case=tc_a09",
      OPTIONS,
    ),
    {
      fromRound: 1,
      toRound: 4,
      evalRound: 3,
      workflow: "edit",
      sortKey: "rule_score",
      sortDir: "asc",
      testCaseId: "tc_a09",
    },
  );
});

test("skill detail params parser falls back for invalid values", () => {
  assert.deepEqual(
    parseSkillDetailParams(
      {
        from: "10",
        to: "nan",
        round: "0",
        workflow: "missing",
        sort: "unknown",
        dir: "sideways",
      },
      OPTIONS,
    ),
    {
      fromRound: 0,
      toRound: 5,
      evalRound: 5,
      workflow: "all",
      sortKey: "hybrid_score",
      sortDir: "desc",
      testCaseId: undefined,
    },
  );
});

test("skill detail query builder writes deterministic params", () => {
  assert.equal(
    buildSkillDetailQuery({
      fromRound: 0,
      toRound: 5,
      evalRound: 5,
      workflow: "all",
      sortKey: "hybrid_score",
      sortDir: "desc",
      testCaseId: "tc_b01",
    }),
    "?from=0&to=5&round=5&workflow=all&sort=hybrid_score&dir=desc&case=tc_b01",
  );
});
