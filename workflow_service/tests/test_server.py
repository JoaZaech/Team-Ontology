import json
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from evidence_service.projection import EvidenceProjection
from evidence_service.server import EvidenceHTTPServer, EvidenceRequestHandler

MOCK_API_ROOT = Path(__file__).resolve().parents[2] / "mock_api"
if str(MOCK_API_ROOT) not in sys.path:
    sys.path.insert(0, str(MOCK_API_ROOT))

from rule_client import RuleServiceClient
from decision_receipts import DecisionReceiptLedger
from rule_service_fixture import running_rule_service
from viseca_mock import MOCK_RUN_ID, RemoteMockVisecaState, build_connection_event
from workflow_service.client import WorkflowServiceClient
from workflow_service.flywheel import EvidenceServiceOutboxPublisher, NullFlywheelPublisher
from workflow_service.inference import DecisionHub, PolicySubsystem
from workflow_service.server import WorkflowHTTPServer, WorkflowRequestHandler, WorkflowServiceState
from workflow_service.workflow import WorkflowState


TOKEN = "workflow-service-test-token-with-at-least-32-characters"
EVIDENCE_TOKEN = "evidence-service-test-token-with-at-least-32-chars"


class KnowledgeGraphReviewSubsystem:
    name = "knowledge_graph"
    required = False

    def assess(self, event):
        return {
            "status": "available",
            "version": "kg-v1",
            "recommendation": "step_up",
            "reason_codes": ["knowledge_graph_review"],
            "evidence_refs": [{"source": "knowledge_graph", "version": "kg-v1"}],
        }


class NeverCalledSubsystem:
    name = "knowledge_graph"
    required = False

    def __init__(self):
        self.called = False

    def assess(self, event):
        self.called = True
        raise AssertionError("hard policy declines must bypass advisory subsystems")


class RecordingFlywheelPublisher(NullFlywheelPublisher):
    def __init__(self):
        self.trigger_count = 0

    def trigger(self):
        self.trigger_count += 1


@contextmanager
def running_workflow_service(rule_client: RuleServiceClient):
    state = WorkflowServiceState(rule_client=rule_client)
    server = WorkflowHTTPServer(("127.0.0.1", 0), WorkflowRequestHandler, state, TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@contextmanager
def running_evidence_service():
    projection = EvidenceProjection()
    server = EvidenceHTTPServer(("127.0.0.1", 0), EvidenceRequestHandler, projection, EVIDENCE_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", projection
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def request(base_url: str, method: str, path: str, body=None, token: str | None = TOKEN):
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    if token is not None:
        headers["X-Workflow-Service-Token"] = token
    call = Request(base_url + path, data=payload, headers=headers, method=method)
    with urlopen(call, timeout=2) as response:
        return response.status, json.loads(response.read())


class WorkflowServiceHTTPTests(unittest.TestCase):
    def test_service_records_the_policy_recommended_decision(self):
        with running_rule_service() as rule_url:
            with running_workflow_service(RuleServiceClient(rule_url)) as workflow_url:
                event = build_connection_event()
                status, envelope = request(workflow_url, "POST", "/v1/authorizations", {
                    "event": event,
                    "runId": MOCK_RUN_ID,
                    "eventId": "EVT_TEST_0001",
                })
                self.assertEqual(status, 201)
                self.assertEqual(envelope["event_id"], "EVT_TEST_0001")
                authorization_id = envelope["authorization_id"]

                status, evaluation = request(
                    workflow_url,
                    "POST",
                    f"/v1/authorizations/{authorization_id}/evaluate",
                    {},
                )
                self.assertEqual(status, 200)
                self.assertIn(evaluation["recommended_decision"], {"approve", "decline", "step_up"})

                status, recorded = request(
                    workflow_url,
                    "POST",
                    f"/v1/authorizations/{authorization_id}/decision",
                    {
                        "authorization_id": authorization_id,
                        "decision": evaluation["recommended_decision"],
                        "reason_codes": evaluation["reason_codes"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(recorded["status"], "recorded")
                self.assertTrue(recorded["decision_receipt_hash"])

                status, flywheel = request(workflow_url, "GET", "/v1/flywheel")
                self.assertEqual(status, 200)
                self.assertEqual(flywheel["pending_count"], 1)
                self.assertEqual(flywheel["published_count"], 0)

                status, workflow_status = request(workflow_url, "GET", f"/v1/authorizations/{authorization_id}")
                self.assertEqual(status, 200)
                self.assertEqual(workflow_status["status"], "step_up" if evaluation["recommended_decision"] == "step_up" else "recorded")

    def test_service_requires_its_own_token(self):
        with running_rule_service() as rule_url:
            with running_workflow_service(RuleServiceClient(rule_url)) as workflow_url:
                with self.assertRaises(HTTPError) as raised:
                    request(workflow_url, "POST", "/v1/authorizations", {}, token=None)
                self.assertEqual(raised.exception.code, 401)
                raised.exception.close()

    def test_viseca_adapter_can_delegate_to_the_workflow_service(self):
        with running_rule_service() as rule_url:
            with running_workflow_service(RuleServiceClient(rule_url)) as workflow_url:
                adapter = RemoteMockVisecaState(
                    WorkflowServiceClient(workflow_url, TOKEN),
                    rule_client=RuleServiceClient(rule_url),
                )
                try:
                    envelope = adapter.next_request()
                    self.assertEqual(envelope["run_id"], MOCK_RUN_ID)
                    evaluation = adapter.evaluate()
                    result = adapter.record_decision(envelope["authorization_id"], {
                        "authorization_id": envelope["authorization_id"],
                        "decision": evaluation["recommended_decision"],
                        "reason_codes": evaluation["reason_codes"],
                    })
                    self.assertEqual(result["status"], "recorded")
                finally:
                    adapter.close()

    def test_hub_allows_a_graph_subsystem_to_escalate_a_policy_approval(self):
        with running_rule_service() as rule_url:
            rule_client = RuleServiceClient(rule_url)
            hub = DecisionHub(PolicySubsystem(rule_client), (KnowledgeGraphReviewSubsystem(),))
            workflow = WorkflowState(rule_client=rule_client, decision_hub=hub)
            try:
                workflow.start(build_connection_event(), MOCK_RUN_ID)
                evaluation = workflow.evaluate()
                self.assertEqual(evaluation["recommended_decision"], "step_up")
                self.assertIn("knowledge_graph_review", evaluation["reason_codes"])
                graph = next(item for item in evaluation["inference"]["subsystems"] if item["name"] == "knowledge_graph")
                self.assertEqual(graph["version"], "kg-v1")
                receipt = workflow.receipt_ledger.get(workflow._receipt_key("evaluation"))
                self.assertIn({"source": "knowledge_graph", "version": "kg-v1"}, receipt["evidence_refs"])
            finally:
                workflow.close()

    def test_hub_keeps_a_policy_decline_terminal(self):
        with running_rule_service() as rule_url:
            rule_client = RuleServiceClient(rule_url)
            policy = rule_client.get_policy()
            rule_client.update_policy({
                "policyId": policy["policyId"],
                "expectedRevision": policy["revision"],
                "patch": {"dailySpendingLimitChf": 10},
            })
            graph = NeverCalledSubsystem()
            workflow = WorkflowState(
                rule_client=rule_client,
                decision_hub=DecisionHub(PolicySubsystem(rule_client), (graph,)),
            )
            try:
                workflow.start(build_connection_event(), MOCK_RUN_ID)
                evaluation = workflow.evaluate()
                self.assertEqual(evaluation["recommended_decision"], "decline")
                self.assertFalse(graph.called)
                self.assertEqual([item["name"] for item in evaluation["inference"]["subsystems"]], ["policy"])
            finally:
                workflow.close()

    def test_final_decision_creates_a_receipt_safe_flywheel_event(self):
        with running_rule_service() as rule_url:
            rule_client = RuleServiceClient(rule_url)
            publisher = RecordingFlywheelPublisher()
            workflow = WorkflowState(rule_client=rule_client, flywheel_publisher=publisher)
            try:
                workflow.start(build_connection_event(), MOCK_RUN_ID)
                evaluation = workflow.evaluate()
                result = workflow.record_decision(workflow.authorization_id, {
                    "authorization_id": workflow.authorization_id,
                    "decision": evaluation["recommended_decision"],
                    "reason_codes": evaluation["reason_codes"],
                })

                pending = workflow.receipt_ledger.pending_outbox_events()
                self.assertEqual(len(pending), 1)
                self.assertEqual(publisher.trigger_count, 1)
                payload = pending[0]["payload"]
                self.assertEqual(payload["event_id"], result["decision_receipt_hash"])
                self.assertEqual(payload["provenance"]["receipt_hash"], result["decision_receipt_hash"])
                self.assertEqual(payload["authorization"]["authorization_id"], workflow.authorization_id)
                self.assertEqual(payload["outcome"]["decision"], evaluation["recommended_decision"])
            finally:
                workflow.close()

    def test_outbox_publishes_a_final_decision_to_the_evidence_service(self):
        with running_rule_service() as rule_url:
            with running_evidence_service() as (evidence_url, projection):
                rule_client = RuleServiceClient(rule_url)
                workflow = WorkflowState(rule_client=rule_client)
                publisher = EvidenceServiceOutboxPublisher(
                    workflow.receipt_ledger,
                    evidence_url,
                    EVIDENCE_TOKEN,
                )
                workflow.flywheel_publisher = publisher
                try:
                    workflow.start(build_connection_event(), MOCK_RUN_ID)
                    evaluation = workflow.evaluate()
                    workflow.record_decision(workflow.authorization_id, {
                        "authorization_id": workflow.authorization_id,
                        "decision": evaluation["recommended_decision"],
                        "reason_codes": evaluation["reason_codes"],
                    })
                    publisher.close()

                    self.assertEqual(projection.status()["event_count"], 1)
                    self.assertEqual(workflow.flywheel_status()["published_count"], 1)
                finally:
                    workflow.close()

    def test_step_up_resolution_updates_final_graph_evidence(self):
        with running_rule_service() as rule_url:
            with running_evidence_service() as (evidence_url, projection):
                rule_client = RuleServiceClient(rule_url)
                workflow = WorkflowState(
                    rule_client=rule_client,
                    decision_hub=DecisionHub(
                        PolicySubsystem(rule_client),
                        (KnowledgeGraphReviewSubsystem(),),
                    ),
                )
                publisher = EvidenceServiceOutboxPublisher(
                    workflow.receipt_ledger,
                    evidence_url,
                    EVIDENCE_TOKEN,
                )
                workflow.flywheel_publisher = publisher
                try:
                    workflow.start(build_connection_event(), MOCK_RUN_ID)
                    evaluation = workflow.evaluate()
                    self.assertEqual(evaluation["recommended_decision"], "step_up")
                    workflow.record_decision(workflow.authorization_id, {
                        "authorization_id": workflow.authorization_id,
                        "decision": "step_up",
                        "reason_codes": evaluation["reason_codes"],
                    })
                    workflow.resolve_decision(workflow.authorization_id, {
                        "authorization_id": workflow.authorization_id,
                        "decision": "approve",
                    })
                    publisher.close()

                    resolved = projection.resolve({
                        "authorization": {
                            "card_id": workflow.event["authorization"]["card_id"],
                            "timestamp": "2099-01-01T00:00:00Z",
                            "merchant": {
                                "merchant_id": workflow.event["authorization"]["merchant"]["merchant_id"],
                            },
                        },
                    })
                    self.assertEqual(projection.status()["event_count"], 2)
                    self.assertEqual(resolved["summary"]["prior_approved_count"], 1)
                finally:
                    workflow.close()

    def test_publisher_reconciles_pending_events_after_workflow_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "workflow-receipts.sqlite3"
            with running_rule_service() as rule_url:
                rule_client = RuleServiceClient(rule_url)
                initial = WorkflowState(
                    rule_client=rule_client,
                    receipt_ledger=DecisionReceiptLedger(receipt_path),
                )
                try:
                    initial.start(build_connection_event(), MOCK_RUN_ID)
                    evaluation = initial.evaluate()
                    initial.record_decision(initial.authorization_id, {
                        "authorization_id": initial.authorization_id,
                        "decision": evaluation["recommended_decision"],
                        "reason_codes": evaluation["reason_codes"],
                    })
                    self.assertEqual(initial.flywheel_status()["pending_count"], 1)
                finally:
                    initial.close()

                with running_evidence_service() as (evidence_url, projection):
                    publisher = EvidenceServiceOutboxPublisher(
                        DecisionReceiptLedger(receipt_path),
                        evidence_url,
                        EVIDENCE_TOKEN,
                    )
                    publisher.start()
                    publisher.close()
                    self.assertEqual(projection.status()["event_count"], 1)


if __name__ == "__main__":
    unittest.main()
