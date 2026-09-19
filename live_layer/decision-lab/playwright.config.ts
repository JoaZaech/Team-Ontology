import { defineConfig, devices } from "@playwright/test";

const ruleServiceToken = "e2e-rule-service-token-with-32-characters";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:8082",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: `mkdir -p '/tmp/team-ontology-e2e-rule-service' && chmod 700 '/tmp/team-ontology-e2e-rule-service' && RULE_SERVICE_API_TOKEN='${ruleServiceToken}' RULE_SERVICE_DB_PATH='/tmp/team-ontology-e2e-rule-service/rules.sqlite3' PYTHONDONTWRITEBYTECODE=1 /usr/local/bin/python3 ../../rule_service/server.py`,
      url: "http://127.0.0.1:8083/healthz",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `RULE_SERVICE_API_TOKEN='${ruleServiceToken}' RULE_SERVICE_URL='http://127.0.0.1:8083' DECISION_RECEIPTS_PATH='/tmp/team-ontology-e2e-receipts.sqlite3' PYTHONDONTWRITEBYTECODE=1 /usr/local/bin/python3 ../../mock_api/viseca_mock.py`,
      url: "http://127.0.0.1:8082/healthz",
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});