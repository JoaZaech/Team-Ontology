import type { Decision, DecisionEnvelope, DecisionRecordResult, EvaluationResult } from "./types";
import type { DynamicWalletPolicy, PolicyUpdateRequest } from "./policy-settings";

const mockApiKey = import.meta.env.VITE_VISECA_MOCK_API_KEY ?? "mock-team-key";

type ApiErrorBody = { error?: unknown };

export interface SubmitDecisionInput {
  authorizationId: string;
  decision: Decision;
  reasonCodes: string[];
}

export interface ResolveDecisionInput {
  authorizationId: string;
  decision: Exclude<Decision, "step_up">;
}

function errorMessage(body: unknown, status: number): string {
  const error = body && typeof body === "object" ? (body as ApiErrorBody).error : undefined;
  if (typeof error === "string") {
    return error;
  }
  return `Request failed with status ${status}.`;
}

async function fetchJson<T>(path: string, init: RequestInit = {}): Promise<T | null> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${mockApiKey}`,
        ...init.headers,
      },
    });
  } catch {
    throw new Error("The decision service could not be reached.");
  }

  if (response.status === 204) return null;

  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    if (response.ok) throw new Error("The decision service returned an invalid response.");
  }

  if (!response.ok) throw new Error(errorMessage(body, response.status));
  return body as T;
}

export async function pullRequest(): Promise<DecisionEnvelope | null> {
  return fetchJson<DecisionEnvelope>("/v1/decision-requests/next?wait=0");
}

export async function evaluateRequest(): Promise<EvaluationResult> {
  const evaluation = await fetchJson<EvaluationResult>("/mock/evaluate", { method: "POST" });
  if (!evaluation) throw new Error("No request is available to evaluate.");
  return evaluation;
}

export async function submitDecision(input: SubmitDecisionInput): Promise<DecisionRecordResult> {
  const result = await fetchJson<DecisionRecordResult>(`/v1/authorizations/${encodeURIComponent(input.authorizationId)}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      authorization_id: input.authorizationId,
      decision: input.decision,
      reason_codes: input.reasonCodes,
    }),
  });
  if (!result) throw new Error("The decision service did not confirm the recorded decision.");
  return result;
}

export async function resolveDecision(input: ResolveDecisionInput): Promise<DecisionRecordResult> {
  const result = await fetchJson<DecisionRecordResult>(`/v1/authorizations/${encodeURIComponent(input.authorizationId)}/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      authorization_id: input.authorizationId,
      decision: input.decision,
    }),
  });
  if (!result) throw new Error("The decision service did not confirm the customer response.");
  return result;
}

export async function resetRequestRun(): Promise<void> {
  await fetchJson("/mock/reset", { method: "POST" });
}

/** Read the server-owned policy snapshot used by the local rule engine. */
export async function getWalletPolicy(): Promise<DynamicWalletPolicy> {
  const policy = await fetchJson<DynamicWalletPolicy>("/mock/policy");
  if (!policy) throw new Error("The policy service returned no policy.");
  return policy;
}

/** Persist a versioned customer policy update before another request is evaluated. */
export async function updateWalletPolicy(request: PolicyUpdateRequest): Promise<DynamicWalletPolicy> {
  const policy = await fetchJson<DynamicWalletPolicy>("/mock/policy", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!policy) throw new Error("The policy service did not confirm the update.");
  return policy;
}
