# Authorization Workflow Service

The workflow service owns authorization lifecycle state, decision receipts,
customer step-up resolution, and activity projection. Its Decision Hub calls
the Policy Service first, then invokes registered advisory subsystems such as
the Knowledge Graph without allowing them to relax a hard policy decision.

## Decision Hub

`workflow_service.inference.DecisionHub` is the central inference engine. A
subsystem implements `name`, `required`, and `assess(event)`, then returns a
versioned assessment with optional evidence references and a `step_up`
recommendation. The hub records all subsystem status and evidence provenance in
the evaluation receipt.

The Policy subsystem is mandatory and authoritative. Advisory subsystems can
add evidence or escalate `approve` to `step_up`; they cannot approve a decline.
A required subsystem that is unavailable also escalates to `step_up`.

## Run locally

Start the Policy Service first, then start the Workflow Service from the
repository root:

```sh
export RULE_SERVICE_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python rule_service/server.py

export WORKFLOW_SERVICE_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m workflow_service.server
```

The workflow service listens on `127.0.0.1:8084` by default. It requires its
own `X-Workflow-Service-Token` on every `/v1/` endpoint; `/healthz` is public.
Set `WORKFLOW_SERVICE_PORT` to choose another loopback port.

To attach an online Knowledge Graph subsystem, configure its endpoint before
starting the workflow service:

```sh
export KNOWLEDGE_GRAPH_SERVICE_URL="http://127.0.0.1:8085"
export KNOWLEDGE_GRAPH_SERVICE_API_TOKEN="<service token>"
export KNOWLEDGE_GRAPH_REQUIRED="true"
```

The Knowledge Graph endpoint is `POST /v1/evidence/resolve`. It receives
`{"event": ...}` and returns `status`, `version`, `recommendation`,
`reason_codes`, and `evidence_refs`.

## Data flywheel

The Workflow Service writes a receipt-safe event to its SQLite outbox in the
same transaction as each final decision receipt. When an Evidence Service is
configured, a background publisher drains pending events at startup and retries
undelivered events every five seconds without delaying authorization responses.
The Evidence Service ingests each receipt idempotently and updates its temporal
knowledge-graph evidence projection before acknowledging delivery.

Start the Evidence Service first:

```sh
export EVIDENCE_SERVICE_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m evidence_service.server
```

Then configure the Workflow Service with the matching endpoint and token:

```sh
export EVIDENCE_SERVICE_URL="http://127.0.0.1:8085"
export EVIDENCE_SERVICE_API_TOKEN="$EVIDENCE_SERVICE_API_TOKEN"
python -m workflow_service.server
```

`GET /v1/flywheel` returns receipt-outbox delivery counts. `GET /v1/activity`
also includes those counts in its receipt-safe `flywheel` field. The Evidence
Service exposes `GET /v1/evidence/status` and `POST /v1/evidence/resolve`; its
resolver excludes equal-time and future receipt events.

## Voice approval with ElevenLabs

Voice approval is optional. When it is configured, recording a `step_up`
decision starts one non-blocking outbound call through the ElevenLabs native
Twilio integration. An unavailable call provider never changes the decision:
the authorization remains `awaiting_customer` until an authenticated
`approve` or `decline` resolution arrives.

Import a Twilio number into ElevenLabs, attach it to an ElevenLabs agent, and
configure these environment variables before starting the Workflow Service:

```sh
export ELEVENLABS_API_KEY="<ElevenLabs API key>"
export ELEVENLABS_AGENT_ID="<ElevenLabs agent ID>"
export ELEVENLABS_PHONE_NUMBER_ID="<imported ElevenLabs phone-number ID>"
export VOICE_APPROVAL_TO_NUMBER="+41791234567"
export VOICE_APPROVAL_API_TOKEN="<random secret of at least 32 characters>"
```

The destination number must use E.164 format. The outbound request supplies
these agent dynamic variables: `authorization_id`, `purchase_description`,
`merchant_name`, `amount`, `currency`, `reason_codes`, and
`approval_window_seconds`.

Configure the agent to state the merchant and amount, ask the customer to say
approve or decline, confirm the answer once, and then call a webhook tool:

| Tool setting | Value |
| --- | --- |
| Name | `resolve_purchase_approval` |
| Method | `POST` |
| URL | `https://<public-workflow-host>/v1/voice-approvals/{authorization_id}/resolution` |
| Path parameter | `authorization_id`, populated from the matching dynamic variable |
| JSON body | `decision`, string, restricted in the prompt to `approve` or `decline` |
| Secret header | `X-Voice-Approval-Token: <VOICE_APPROVAL_API_TOKEN>` |

The public host must terminate HTTPS and forward this route to the Workflow
Service. Keep the secret as an ElevenLabs tool secret; do not put it in the
agent prompt or in source control. The endpoint accepts only the two final
decisions and only while the matching authorization is waiting for customer
resolution. `GET /v1/authorizations/{id}` includes `approval_call` status for
operational checks without exposing the API key or destination phone number.

## Use with the Viseca mock

The mock remains the local Viseca protocol adapter and static Decision Lab
host. Set these variables before starting it to forward workflow operations to
the separate service:

```sh
export WORKFLOW_SERVICE_URL="http://127.0.0.1:8084"
export WORKFLOW_SERVICE_API_TOKEN="$WORKFLOW_SERVICE_API_TOKEN"
python mock_api/viseca_mock.py
```

Without `WORKFLOW_SERVICE_URL`, the mock uses the extracted workflow core in
process for backwards-compatible local demos.

## HTTP surface

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/authorizations` | Start one normalized authorization workflow. |
| `POST /v1/authorizations/{id}/evaluate` | Request the deterministic policy evaluation. |
| `POST /v1/authorizations/{id}/decision` | Persist the policy-matching decision and receipt. |
| `POST /v1/authorizations/{id}/resolution` | Persist a customer resolution after step-up. |
| `POST /v1/voice-approvals/{id}/resolution` | Persist an ElevenLabs voice response using its dedicated token. |
| `GET /v1/authorizations/{id}` | Read the receipt-safe workflow status. |
| `GET /v1/activity` | Read the asynchronous activity projection. |
| `GET /v1/observability` | Read bounded aggregate telemetry. |

Run the focused contract suite from the repository root:

```sh
.venv/bin/python -m unittest workflow_service.tests.test_server -v
```
