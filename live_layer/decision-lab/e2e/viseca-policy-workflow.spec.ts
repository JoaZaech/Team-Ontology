import { expect, test, type APIRequestContext, type Response, type TestInfo } from "@playwright/test";

const authorizationHeaders = { Authorization: "Bearer mock-team-key" };

type WalletPolicy = {
  policyId: string;
  revision: number;
  enabled: boolean;
  dailySpendingLimitChf: number;
  reviewTriggers: string[];
  assistantAuthority: string;
};

type BenchmarkEvaluation = {
  authorization_id: string;
  source_authorization_id: string;
  recommended_decision: "approve" | "decline" | "step_up";
  reason_codes: string[];
  duration_ms: number;
};

function percentile(values: number[], fraction: number): number {
  const sorted = [...values].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * fraction) - 1)] ?? 0;
}

async function attachRuntime(testInfo: TestInfo, metrics: Record<string, unknown>): Promise<void> {
  await testInfo.attach("runtime-metrics", {
    body: Buffer.from(JSON.stringify(metrics, null, 2)),
    contentType: "application/json",
  });
  console.log(`[runtime] ${testInfo.title}: ${JSON.stringify(metrics)}`);
}

async function restoreWalletPolicy(request: APIRequestContext): Promise<WalletPolicy> {
  const currentResponse = await request.get("/mock/policy", { headers: authorizationHeaders });
  expect(currentResponse.ok()).toBeTruthy();
  const current = await currentResponse.json() as WalletPolicy;
  const updateResponse = await request.patch("/mock/policy", {
    headers: authorizationHeaders,
    data: {
      policyId: current.policyId,
      expectedRevision: current.revision,
      patch: {
        enabled: true,
        dailySpendingLimitChf: 1500,
        reviewTriggers: ["new_merchant"],
        assistantAuthority: "trusted",
      },
    },
  });
  expect(updateResponse.ok()).toBeTruthy();
  return updateResponse.json() as Promise<WalletPolicy>;
}

async function responseDurationMs(response: Response): Promise<number> {
  await response.finished();
  return response.request().timing().responseEnd;
}

test.describe.configure({ mode: "serial" });

test("replays all 45 Viseca CSV attempts through the mock API and rule engine", async ({ request }, testInfo) => {
  await restoreWalletPolicy(request);
  const startedAt = performance.now();
  const startResponse = await request.post("/mock/benchmark/runs", {
    headers: authorizationHeaders,
    data: { scenario_id: "all" },
  });
  expect(startResponse.ok()).toBeTruthy();
  const started = await startResponse.json() as { runs: Array<{ run_id: string; scenario_id: string; event_count: number }> };
  expect(started.runs.map((run) => [run.scenario_id, run.event_count])).toEqual([
    ["SCEN0000", 1],
    ["SCEN0001", 10],
    ["SCEN0002", 12],
    ["SCEN0003", 11],
    ["SCEN0004", 11],
  ]);

  const sourceAuthorizationIds = new Set<string>();
  const recommendations = new Set<string>();
  const engineDurationsMs: number[] = [];

  for (const run of started.runs) {
    for (;;) {
      const nextResponse = await request.get(`/mock/benchmark/runs/${run.run_id}/next`, {
        headers: authorizationHeaders,
      });
      if (nextResponse.status() === 204) break;
      expect(nextResponse.ok()).toBeTruthy();
      const envelope = await nextResponse.json() as {
        authorization_id: string;
        source_authorization_id: string;
      };
      expect(sourceAuthorizationIds.has(envelope.source_authorization_id)).toBeFalsy();
      sourceAuthorizationIds.add(envelope.source_authorization_id);

      const evaluationResponse = await request.post(`/mock/benchmark/runs/${run.run_id}/evaluate`, {
        headers: authorizationHeaders,
        data: {},
      });
      expect(evaluationResponse.ok()).toBeTruthy();
      const evaluation = await evaluationResponse.json() as BenchmarkEvaluation;
      expect(evaluation.authorization_id).toBe(envelope.authorization_id);
      expect(evaluation.source_authorization_id).toBe(envelope.source_authorization_id);
      expect(evaluation.reason_codes).toEqual(expect.any(Array));
      expect(evaluation.duration_ms).toBeGreaterThanOrEqual(0);
      engineDurationsMs.push(evaluation.duration_ms);
      recommendations.add(evaluation.recommended_decision);

      const decisionResponse = await request.post(
        `/mock/benchmark/runs/${run.run_id}/authorizations/${envelope.authorization_id}/decision`,
        {
          headers: authorizationHeaders,
          data: {
            authorization_id: envelope.authorization_id,
            decision: evaluation.recommended_decision,
            reason_codes: evaluation.reason_codes,
          },
        },
      );
      expect(decisionResponse.ok()).toBeTruthy();

      if (evaluation.recommended_decision === "step_up") {
        const resolutionResponse = await request.post(
          `/mock/benchmark/runs/${run.run_id}/authorizations/${envelope.authorization_id}/resolve`,
          {
            headers: authorizationHeaders,
            data: { authorization_id: envelope.authorization_id, decision: "decline" },
          },
        );
        expect(resolutionResponse.ok()).toBeTruthy();
      }
    }

    const summaryResponse = await request.get(`/mock/benchmark/runs/${run.run_id}`, {
      headers: authorizationHeaders,
    });
    expect(summaryResponse.ok()).toBeTruthy();
    const summary = await summaryResponse.json() as {
      status: string;
      completed_count: number;
      event_count: number;
      receipt_chain_valid: boolean;
    };
    expect(summary.status).toBe("completed");
    expect(summary.completed_count).toBe(summary.event_count);
    expect(summary.receipt_chain_valid).toBeTruthy();
  }

  expect(sourceAuthorizationIds.size).toBe(45);
  expect([...sourceAuthorizationIds].sort()).toEqual(
    Array.from({ length: 45 }, (_, index) => `AU${String(index + 1).padStart(4, "0")}`),
  );
  expect(recommendations).toEqual(new Set(["approve", "decline", "step_up"]));

  await attachRuntime(testInfo, {
    totalAttempts: sourceAuthorizationIds.size,
    totalRuntimeMs: Number((performance.now() - startedAt).toFixed(2)),
    engineEvaluationMs: {
      p50: Number(percentile(engineDurationsMs, 0.5).toFixed(2)),
      p95: Number(percentile(engineDurationsMs, 0.95).toFixed(2)),
      max: Number(Math.max(...engineDurationsMs).toFixed(2)),
    },
  });
});

test("approves the supplied AU0001 fixture through the frontend workflow", async ({ page, request }, testInfo) => {
  await restoreWalletPolicy(request);
  const startedAt = performance.now();
  const requestResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/v1/decision-requests/next") && response.status() === 200,
  );
  const evaluationResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/mock/evaluate") && response.status() === 200,
  );
  const decisionResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/decision") && response.status() === 200,
  );

  await page.goto("/#workflow");
  await expect(page.getByRole("heading", { name: "Approved. Ready to continue." })).toBeVisible();

  const requestBody = await (await requestResponsePromise).json();
  expect(requestBody.data.authorization.source_authorization_id).toBe("AU0001");
  expect(requestBody.data.authorization.scenario_id).toBe("SCEN0000");
  expect(requestBody.data.authorization.merchant.merchant_name).toBe("Alpine Basket");
  expect(requestBody.data.authorization.billing_amount_chf).toBe(20);
  expect(requestBody.data.agent_proposal).toMatchObject({
    summary: "Grocery delivery order",
    merchant_name: "Alpine Basket",
    items_subtotal_chf: 13,
    delivery_fee_chf: 7,
    total_chf: 20,
  });
  expect(requestBody.data.applied_policies.wallet_policy).toMatchObject({
    daily_spending_limit_chf: 1500,
    assistant_authority: "trusted",
  });

  const evaluationResponse = await evaluationResponsePromise;
  const evaluation = await evaluationResponse.json();
  expect(evaluation.recommended_decision).toBe("approve");
  expect(evaluation.checks.every((check: { outcome: string }) => check.outcome === "pass")).toBeTruthy();
  expect(evaluation.checks.find((check: { name: string }) => check.name === "Merchant familiarity")?.detail).toContain("26 prior approved purchases");

  const decisionBody = await (await decisionResponsePromise).json();
  expect(decisionBody).toMatchObject({ status: "recorded", decision: "approve" });
  await expect(page.getByText("The purchase matches your wallet policy.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "What the agent asked to buy" })).toBeVisible();
  await expect(page.getByText("Grocery delivery order")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Rules used for this decision" })).toBeVisible();
  await expect(page.getByText("Purchase total <= CHF 20.00.")).toBeVisible();

  await attachRuntime(testInfo, {
    totalWorkflowMs: Number((performance.now() - startedAt).toFixed(2)),
    ruleEngineHttpMs: Number((await responseDurationMs(evaluationResponse)).toFixed(2)),
  });
});

test("enforces a CHF 10 policy change and declines AU0001 in the frontend", async ({ page, request }, testInfo) => {
  await restoreWalletPolicy(request);
  await page.goto("/#settings");
  await expect(page.getByRole("heading", { name: "Wallet policies" })).toBeVisible();

  const limitInput = page.getByLabel("Daily spending limit in CHF");
  await expect(limitInput).toHaveValue("1500");
  const policyResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/mock/policy") && response.request().method() === "PATCH",
  );
  await limitInput.fill("10");
  await limitInput.press("Tab");
  const policyResponse = await policyResponsePromise;
  expect(policyResponse.ok()).toBeTruthy();
  expect((await policyResponse.json()).dailySpendingLimitChf).toBe(10);
  await expect(page.getByText("Dynamic wallet policy updated. New purchase requests will use this revision.")).toBeVisible();

  const startedAt = performance.now();
  const requestResponsePromise = page.waitForResponse(
    (response) => response.url().includes("/v1/decision-requests/next") && response.status() === 200,
  );
  const evaluationResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/mock/evaluate") && response.status() === 200,
  );
  const decisionResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/decision") && response.status() === 200,
  );
  await page.getByRole("button", { name: "Open agent simulation" }).click();
  await expect(page.getByRole("heading", { name: "Declined. No payment was approved." })).toBeVisible();

  const requestBody = await (await requestResponsePromise).json();
  expect(requestBody.data.authorization.source_authorization_id).toBe("AU0001");
  const evaluationResponse = await evaluationResponsePromise;
  const evaluation = await evaluationResponse.json();
  expect(evaluation.recommended_decision).toBe("decline");
  expect(evaluation.checks.find((check: { name: string }) => check.name === "Daily spending limit")).toMatchObject({
    outcome: "fail",
    reason_code: "daily_spending_limit_exceeded",
  });
  expect(await (await decisionResponsePromise).json()).toMatchObject({ status: "recorded", decision: "decline" });
  await expect(page.getByText("This purchase exceeds the daily spending limit")).toBeVisible();
  await expect(page.getByRole("heading", { name: "What the agent asked to buy" })).toBeVisible();
  await expect(page.getByText("Up to CHF 10.00 per day.")).toBeVisible();

  await attachRuntime(testInfo, {
    policyUpdateHttpMs: Number((await responseDurationMs(policyResponse)).toFixed(2)),
    totalWorkflowMs: Number((performance.now() - startedAt).toFixed(2)),
    ruleEngineHttpMs: Number((await responseDurationMs(evaluationResponse)).toFixed(2)),
  });
});