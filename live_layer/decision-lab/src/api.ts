import { AUTHORIZATION_ID, FIXTURE_ENVELOPE, FIXTURE_EVALUATION } from "./fixtures";
import type { Decision, DecisionEnvelope, DecisionRecordResult, EvaluationResult } from "./types";

/**
 * Local, static stand-in for the Viseca mock API. No fetch(), no server —
 * this module just replays one fixture purchase from memory, mirroring the
 * request/response shapes and single-delivery semantics of
 * `live_layer/viseca_mock.py` so the UI and its logic stay unchanged.
 */

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

let delivered = false;
let recordedDecision: Decision | null = null;

/** Pulls the queued mock purchase. Resolves to null when it was already delivered. */
export async function pullRequest(): Promise<DecisionEnvelope | null> {
  await sleep(250);
  if (delivered) return null;
  delivered = true;
  return FIXTURE_ENVELOPE;
}

export async function evaluateRequest(): Promise<EvaluationResult> {
  await sleep(600);
  if (!delivered) throw new Error("request_not_delivered");
  return FIXTURE_EVALUATION;
}

export interface SubmitDecisionInput {
  authorizationId: string;
  decision: Decision;
  reasonCodes: string[];
  engineVersion: string;
}

export async function submitDecision(input: SubmitDecisionInput): Promise<DecisionRecordResult> {
  await sleep(250);
  if (input.authorizationId !== AUTHORIZATION_ID) throw new Error("unknown_authorization");
  if (!delivered) throw new Error("request_not_delivered");
  if (recordedDecision !== null && recordedDecision !== input.decision) {
    throw new Error("decision_conflict");
  }
  recordedDecision = input.decision;
  return { authorization_id: input.authorizationId, status: "recorded", decision: input.decision };
}

export async function resetDemo(): Promise<void> {
  await sleep(150);
  delivered = false;
  recordedDecision = null;
}
