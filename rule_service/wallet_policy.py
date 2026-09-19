"""Versioned customer wallet policy and deterministic policy checks.

This module deliberately has no HTTP or browser dependency.  It accepts a
canonical Viseca-shaped event plus trusted history loaded from the synthetic
data pack, and returns explainable checks suitable for a decision receipt.
The agent proposal is never treated as a source of policy or history facts.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
from secrets import token_urlsafe
import sqlite3
import stat
from threading import RLock
from typing import Any, Callable, Mapping

from benchmark_policy import (
    BenchmarkPolicyValidationError,
    benchmark_policy_documents,
    validate_event_binding,
    validate_scenario_policy_document,
)


REVIEW_TRIGGERS = frozenset({"new_merchant", "online_purchase", "unusual_activity"})
ASSISTANT_AUTHORITIES = frozenset({"review", "trusted", "autopilot"})
SPEND_CATEGORIES = ("Groceries", "Transport", "Dining", "Shopping")

# The policy UI uses customer-facing labels while the Viseca data pack uses a
# stable lowercase vocabulary.  This mapping is intentionally explicit rather
# than inferred from merchant-provided text.
CATEGORY_TO_DATASET = {
    "Groceries": frozenset({"groceries"}),
    "Transport": frozenset({"transport", "fuel"}),
    "Dining": frozenset({"dining", "food_delivery"}),
    "Shopping": frozenset({"books", "clothing", "cosmetics", "electronics", "gift_card", "health", "home_improvement", "household", "sporting_goods"}),
}


class PolicyValidationError(ValueError):
    """Raised when a customer-policy update cannot be made executable."""


class PolicyConflictError(PolicyValidationError):
    """Raised when a write was based on an obsolete policy revision."""


class PolicyIntegrityError(PolicyValidationError):
    """Raised when a persisted policy no longer matches its integrity record."""


def _money(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise PolicyValidationError(f"{field} must be a number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PolicyValidationError(f"{field} must be a number") from exc
    if not result.is_finite() or result < 0:
        raise PolicyValidationError(f"{field} must be a non-negative finite number")
    return result


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def default_wallet_policy_document() -> dict[str, Any]:
    """Return the server-owned default used by the local demonstration.

    The confirmed mandate still has the stricter CHF 20 purchase ceiling.  The
    dynamic policy adds an independent daily limit, category limits, and a
    customer-selected prompt for a first purchase with a merchant.
    """

    return {
        "policyId": "wallet-policy_CA0001_default",
        "schemaVersion": "2026-09-01",
        "revision": 1,
        "subject": {"customerId": "CU0001", "cardId": "CA0001"},
        "enabled": True,
        "dailySpendingLimitChf": 1500,
        "adaptiveSpendProfiles": {
            "Groceries": {
                "maximumChf": 180,
                "typicalRange": "CHF 35–180",
                "explanation": "Derived from the supplied card transaction history.",
            },
            "Transport": {
                "maximumChf": 90,
                "typicalRange": "CHF 12–90",
                "explanation": "Derived from the supplied card transaction history.",
            },
            "Dining": {
                "maximumChf": 140,
                "typicalRange": "CHF 25–140",
                "explanation": "Derived from the supplied card transaction history.",
            },
            "Shopping": {
                "maximumChf": 250,
                "typicalRange": "CHF 40–250",
                "explanation": "Derived from the supplied card transaction history.",
            },
        },
        "reviewTriggers": ["new_merchant"],
        "assistantAuthority": "trusted",
        "effectiveFrom": "2026-09-19T00:00:00.000Z",
        "updatedAt": "2026-09-19T10:42:00.000Z",
        "updatedBy": "customer",
    }


def _validate_profiles(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) != set(SPEND_CATEGORIES):
        raise PolicyValidationError("adaptiveSpendProfiles must contain every supported category")
    profiles: dict[str, dict[str, Any]] = {}
    for category in SPEND_CATEGORIES:
        profile = value[category]
        if not isinstance(profile, Mapping):
            raise PolicyValidationError(f"{category} profile must be an object")
        maximum = _money(profile.get("maximumChf"), f"{category} maximumChf")
        typical_range = profile.get("typicalRange")
        explanation = profile.get("explanation")
        if not isinstance(typical_range, str) or not isinstance(explanation, str):
            raise PolicyValidationError(f"{category} profile text is invalid")
        profiles[category] = {
            "maximumChf": float(maximum),
            "typicalRange": typical_range,
            "explanation": explanation,
        }
    return profiles


def validate_policy_patch(patch: Any) -> dict[str, Any]:
    """Validate a UI policy patch before it can reach the evaluator."""

    if not isinstance(patch, Mapping):
        raise PolicyValidationError("patch must be an object")
    allowed = {
        "enabled",
        "dailySpendingLimitChf",
        "adaptiveSpendProfiles",
        "reviewTriggers",
        "assistantAuthority",
    }
    unexpected = set(patch) - allowed
    if unexpected:
        raise PolicyValidationError("policy patch contains unsupported fields")

    validated: dict[str, Any] = {}
    if "enabled" in patch:
        if not isinstance(patch["enabled"], bool):
            raise PolicyValidationError("enabled must be a boolean")
        validated["enabled"] = patch["enabled"]
    if "dailySpendingLimitChf" in patch:
        validated["dailySpendingLimitChf"] = float(
            _money(patch["dailySpendingLimitChf"], "dailySpendingLimitChf")
        )
    if "adaptiveSpendProfiles" in patch:
        validated["adaptiveSpendProfiles"] = _validate_profiles(patch["adaptiveSpendProfiles"])
    if "reviewTriggers" in patch:
        triggers = patch["reviewTriggers"]
        if (
            not isinstance(triggers, list)
            or any(not isinstance(trigger, str) for trigger in triggers)
            or len(set(triggers)) != len(triggers)
            or not set(triggers).issubset(REVIEW_TRIGGERS)
        ):
            raise PolicyValidationError("reviewTriggers contains an unsupported trigger")
        validated["reviewTriggers"] = list(triggers)
    if "assistantAuthority" in patch:
        authority = patch["assistantAuthority"]
        if authority not in ASSISTANT_AUTHORITIES:
            raise PolicyValidationError("assistantAuthority is unsupported")
        validated["assistantAuthority"] = authority
    return validated


class WalletPolicyStore:
    """Small in-memory, versioned store used by the local mock services.

    It models the same optimistic-concurrency contract the frontend exposes.
    Production storage belongs behind this boundary; the pure evaluator only
    receives an immutable snapshot from ``get``.
    """

    def __init__(self, initial: Mapping[str, Any] | None = None):
        self._stored = deepcopy(dict(initial or default_wallet_policy_document()))

    def get(self) -> dict[str, Any]:
        return deepcopy(self._stored)

    def update(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise PolicyValidationError("policy update must be an object")
        if set(request) != {"policyId", "expectedRevision", "patch"}:
            raise PolicyValidationError("policy update fields are invalid")
        if request["policyId"] != self._stored["policyId"]:
            raise PolicyValidationError("policy not found")
        revision = request["expectedRevision"]
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise PolicyValidationError("expectedRevision must be an integer")
        if revision != self._stored["revision"]:
            raise PolicyConflictError("policy revision conflict")
        patch = validate_policy_patch(request["patch"])
        self._stored = {
            **self._stored,
            **deepcopy(patch),
            "revision": self._stored["revision"] + 1,
            "updatedAt": _iso_now(),
            "updatedBy": "customer",
        }
        return self.get()


def _canonical_document(document: Mapping[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _document_digest(document: Mapping[str, Any]) -> str:
    return f"sha256:{sha256(_canonical_document(document).encode('utf-8')).hexdigest()}"


def _validate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, Mapping):
        raise PolicyValidationError("policy document must be an object")
    required = {
        "policyId", "schemaVersion", "revision", "subject", "enabled",
        "dailySpendingLimitChf", "adaptiveSpendProfiles", "reviewTriggers",
        "assistantAuthority", "effectiveFrom", "updatedAt", "updatedBy",
    }
    if set(document) != required:
        raise PolicyValidationError("policy document fields are invalid")
    policy_id = document["policyId"]
    if not isinstance(policy_id, str) or not policy_id or len(policy_id) > 128:
        raise PolicyValidationError("policyId is invalid")
    if not isinstance(document["schemaVersion"], str) or not document["schemaVersion"]:
        raise PolicyValidationError("schemaVersion is invalid")
    revision = document["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise PolicyValidationError("revision is invalid")
    subject = document["subject"]
    if (not isinstance(subject, Mapping) or set(subject) != {"customerId", "cardId"}
            or not all(isinstance(subject[field], str) and subject[field]
                       for field in ("customerId", "cardId"))):
        raise PolicyValidationError("policy subject is invalid")
    if not all(isinstance(document[field], str) and document[field]
               for field in ("effectiveFrom", "updatedAt", "updatedBy")):
        raise PolicyValidationError("policy audit fields are invalid")
    fields = validate_policy_patch({
        key: document[key]
        for key in (
            "enabled", "dailySpendingLimitChf", "adaptiveSpendProfiles",
            "reviewTriggers", "assistantAuthority",
        )
    })
    return {
        "policyId": policy_id,
        "schemaVersion": document["schemaVersion"],
        "revision": revision,
        "subject": {"customerId": subject["customerId"], "cardId": subject["cardId"]},
        **fields,
        "effectiveFrom": document["effectiveFrom"],
        "updatedAt": document["updatedAt"],
        "updatedBy": document["updatedBy"],
    }


class SQLiteWalletPolicyStore:
    """Local durable policy store with validated documents and immutable revisions."""

    def __init__(self, database_path: str | Path, initial: Mapping[str, Any] | None = None):
        self.database_path = Path(database_path)
        self._lock = RLock()
        self._prepare_path()
        self._connection = sqlite3.connect(
            self.database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute("PRAGMA synchronous = FULL")
        self._create_schema()
        self._seed(initial or default_wallet_policy_document())
        self._seed_scenario_policies()
        self._lock_database_files()

    def _prepare_path(self) -> None:
        parent_missing = not self.database_path.parent.exists()
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if parent_missing:
            os.chmod(self.database_path.parent, 0o700)
        parent_status = self.database_path.parent.lstat()
        if (stat.S_ISLNK(parent_status.st_mode) or not stat.S_ISDIR(parent_status.st_mode)
                or parent_status.st_uid != os.geteuid()
                or parent_status.st_mode & 0o077):
            raise PolicyIntegrityError("policy database directory must be private and owned by this user")
        if not self.database_path.exists():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self.database_path, flags, 0o600)
            os.close(descriptor)
        self._lock_database_files()

    def _lock_database_files(self) -> None:
        for path in (
            self.database_path,
            self.database_path.with_name(f"{self.database_path.name}-wal"),
            self.database_path.with_name(f"{self.database_path.name}-shm"),
        ):
            if path.exists():
                status = path.lstat()
                if (stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode)
                        or status.st_uid != os.geteuid() or status.st_nlink != 1):
                    raise PolicyIntegrityError("policy database file must be a private regular file")
                os.chmod(path, 0o600)

    def _create_schema(self) -> None:
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS policies (
                policy_id TEXT PRIMARY KEY,
                card_id TEXT NOT NULL UNIQUE,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                document_json TEXT NOT NULL,
                document_digest TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS policy_revisions (
                policy_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                document_json TEXT NOT NULL,
                document_digest TEXT NOT NULL,
                previous_digest TEXT,
                changed_at TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                PRIMARY KEY(policy_id, revision),
                FOREIGN KEY(policy_id) REFERENCES policies(policy_id)
            );
            CREATE TABLE IF NOT EXISTS scenario_policies (
                policy_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                card_id TEXT NOT NULL,
                customer_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                document_json TEXT NOT NULL,
                document_digest TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                UNIQUE(scenario_id, card_id)
            );
            CREATE TABLE IF NOT EXISTS scenario_policy_revisions (
                policy_id TEXT NOT NULL,
                revision INTEGER NOT NULL CHECK(revision >= 1),
                document_json TEXT NOT NULL,
                document_digest TEXT NOT NULL,
                previous_digest TEXT,
                changed_at TEXT NOT NULL,
                changed_by TEXT NOT NULL,
                PRIMARY KEY(policy_id, revision),
                FOREIGN KEY(policy_id) REFERENCES scenario_policies(policy_id)
            );
            CREATE TABLE IF NOT EXISTS policy_runs (
                run_id TEXT PRIMARY KEY,
                policy_id TEXT NOT NULL,
                scenario_id TEXT NOT NULL,
                card_id TEXT NOT NULL,
                policy_revision INTEGER NOT NULL CHECK(policy_revision >= 1),
                policy_snapshot_json TEXT NOT NULL,
                policy_snapshot_digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(policy_id) REFERENCES scenario_policies(policy_id)
            );
            CREATE TABLE IF NOT EXISTS policy_run_evaluations (
                run_id TEXT NOT NULL,
                authorization_id TEXT NOT NULL,
                event_digest TEXT NOT NULL,
                event_json TEXT NOT NULL,
                evaluation_json TEXT NOT NULL,
                approved_state_digest TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                PRIMARY KEY(run_id, authorization_id),
                FOREIGN KEY(run_id) REFERENCES policy_runs(run_id)
            );
            CREATE TABLE IF NOT EXISTS policy_run_decisions (
                run_id TEXT NOT NULL,
                authorization_id TEXT NOT NULL,
                submitted_decision TEXT NOT NULL CHECK(submitted_decision IN ('approve', 'decline', 'step_up')),
                final_decision TEXT CHECK(final_decision IN ('approve', 'decline')),
                customer_confirmed INTEGER NOT NULL CHECK(customer_confirmed IN (0, 1)),
                committed_at TEXT NOT NULL,
                PRIMARY KEY(run_id, authorization_id),
                FOREIGN KEY(run_id, authorization_id)
                    REFERENCES policy_run_evaluations(run_id, authorization_id)
            );
        """)

    def _seed(self, document: Mapping[str, Any]) -> None:
        with self._lock:
            count = self._connection.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
            if count == 0:
                self.create(document)

    def _seed_scenario_policies(self) -> None:
        for document in benchmark_policy_documents():
            with self._lock:
                row = self._connection.execute(
                    "SELECT policy_id FROM scenario_policies WHERE policy_id = ?",
                    (document["policyId"],),
                ).fetchone()
            if row is None:
                self.create_scenario_policy(document)

    def _decode_scenario_row(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            document = json.loads(row["document_json"])
            validated = validate_scenario_policy_document(document)
        except (TypeError, json.JSONDecodeError, BenchmarkPolicyValidationError) as exc:
            raise PolicyIntegrityError("persisted scenario policy is invalid") from exc
        if _document_digest(validated) != row["document_digest"]:
            raise PolicyIntegrityError("persisted scenario policy integrity check failed")
        if (
            validated["policyId"] != row["policy_id"]
            or validated["scenarioId"] != row["scenario_id"]
            or validated["subject"]["cardId"] != row["card_id"]
            or validated["subject"]["customerId"] != row["customer_id"]
            or validated["revision"] != row["revision"]
        ):
            raise PolicyIntegrityError("persisted scenario policy identity check failed")
        return validated

    def _verify_scenario_revision_chain(
        self, current: sqlite3.Row, document: Mapping[str, Any]
    ) -> None:
        rows = self._connection.execute(
            "SELECT revision, document_json, document_digest, previous_digest FROM scenario_policy_revisions WHERE policy_id = ? ORDER BY revision",
            (document["policyId"],),
        ).fetchall()
        previous_digest: str | None = None
        for expected_revision, row in enumerate(rows, start=1):
            if row["revision"] != expected_revision or row["previous_digest"] != previous_digest:
                raise PolicyIntegrityError("persisted scenario policy revision chain is invalid")
            try:
                revision_document = validate_scenario_policy_document(json.loads(row["document_json"]))
            except (TypeError, json.JSONDecodeError, BenchmarkPolicyValidationError) as exc:
                raise PolicyIntegrityError("persisted scenario policy revision is invalid") from exc
            if (
                revision_document["policyId"] != document["policyId"]
                or revision_document["revision"] != expected_revision
                or _document_digest(revision_document) != row["document_digest"]
            ):
                raise PolicyIntegrityError("persisted scenario policy revision integrity check failed")
            previous_digest = row["document_digest"]
        if (
            not rows
            or document["revision"] != len(rows)
            or current["document_digest"] != previous_digest
        ):
            raise PolicyIntegrityError("persisted scenario policy revision chain is incomplete")

    def _scenario_row_for(
        self, policy_id: str | None = None, scenario_id: str | None = None, card_id: str | None = None
    ) -> sqlite3.Row:
        if policy_id is not None:
            row = self._connection.execute(
                "SELECT * FROM scenario_policies WHERE policy_id = ?", (policy_id,)
            ).fetchone()
        elif scenario_id is not None and card_id is not None:
            row = self._connection.execute(
                "SELECT * FROM scenario_policies WHERE scenario_id = ? AND card_id = ?",
                (scenario_id, card_id),
            ).fetchone()
        else:
            raise PolicyValidationError("scenario policy lookup is invalid")
        if row is None:
            raise PolicyValidationError("scenario policy not found")
        return row

    def get_scenario_policy(self, scenario_id: str, card_id: str) -> dict[str, Any]:
        if not all(isinstance(value, str) and value for value in (scenario_id, card_id)):
            raise PolicyValidationError("scenario policy binding is invalid")
        with self._lock:
            row = self._scenario_row_for(scenario_id=scenario_id, card_id=card_id)
            document = self._decode_scenario_row(row)
            self._verify_scenario_revision_chain(row, document)
            return deepcopy(document)

    def get_scenario_policy_by_id(self, policy_id: str) -> dict[str, Any]:
        if not isinstance(policy_id, str) or not policy_id:
            raise PolicyValidationError("scenario policy not found")
        with self._lock:
            row = self._scenario_row_for(policy_id=policy_id)
            document = self._decode_scenario_row(row)
            self._verify_scenario_revision_chain(row, document)
            return deepcopy(document)

    def list_scenario_policies(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM scenario_policies ORDER BY scenario_id, card_id"
            ).fetchall()
            documents = []
            for row in rows:
                document = self._decode_scenario_row(row)
                self._verify_scenario_revision_chain(row, document)
                documents.append(document)
            return deepcopy(documents)

    def create_scenario_policy(self, document: Any) -> dict[str, Any]:
        try:
            stored = validate_scenario_policy_document(document)
        except BenchmarkPolicyValidationError as exc:
            raise PolicyValidationError(str(exc)) from exc
        if stored["revision"] != 1:
            raise PolicyValidationError("new scenario policy revision must be 1")
        serialized = _canonical_document(stored)
        digest = _document_digest(stored)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "INSERT INTO scenario_policies(policy_id, scenario_id, card_id, customer_id, revision, document_json, document_digest, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        stored["policyId"],
                        stored["scenarioId"],
                        stored["subject"]["cardId"],
                        stored["subject"]["customerId"],
                        stored["revision"],
                        serialized,
                        digest,
                        stored["updatedAt"],
                        stored["updatedBy"],
                    ),
                )
                self._connection.execute(
                    "INSERT INTO scenario_policy_revisions(policy_id, revision, document_json, document_digest, previous_digest, changed_at, changed_by) VALUES (?, ?, ?, ?, NULL, ?, ?)",
                    (
                        stored["policyId"],
                        stored["revision"],
                        serialized,
                        digest,
                        stored["updatedAt"],
                        stored["updatedBy"],
                    ),
                )
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._connection.execute("ROLLBACK")
                raise PolicyConflictError("scenario policy already exists for this scenario or card") from exc
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            self._lock_database_files()
        return deepcopy(stored)

    def _wallet_policy_for_card_or_none(self, card_id: str) -> dict[str, Any] | None:
        try:
            return self.get_for_card(card_id)
        except PolicyValidationError as exc:
            if str(exc) != "policy not found":
                raise
            return None

    def policy_snapshot_for_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        try:
            authorization = event["authorization"]
            scenario_id = authorization["scenario_id"]
            card_id = authorization["card_id"]
        except (KeyError, TypeError) as exc:
            raise PolicyValidationError("event policy binding is invalid") from exc
        scenario_policy = self.get_scenario_policy(scenario_id, card_id)
        try:
            validate_event_binding(scenario_policy, event)
        except BenchmarkPolicyValidationError as exc:
            raise PolicyValidationError(str(exc)) from exc
        wallet_policy = self._wallet_policy_for_card_or_none(card_id)
        return {
            "policyId": scenario_policy["policyId"],
            "revision": scenario_policy["revision"],
            "scenarioId": scenario_policy["scenarioId"],
            "subject": deepcopy(scenario_policy["subject"]),
            "scenarioPolicy": scenario_policy,
            "walletPolicy": wallet_policy,
        }

    def _run_row_for(self, run_id: str) -> sqlite3.Row:
        if not isinstance(run_id, str) or not run_id:
            raise PolicyValidationError("run not found")
        row = self._connection.execute(
            "SELECT * FROM policy_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise PolicyValidationError("run not found")
        return row

    def _decode_run_snapshot(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            snapshot = json.loads(row["policy_snapshot_json"])
            if not isinstance(snapshot, Mapping):
                raise TypeError("snapshot must be an object")
            scenario_policy = validate_scenario_policy_document(snapshot["scenarioPolicy"])
            wallet_policy = snapshot.get("walletPolicy")
            if wallet_policy is not None:
                wallet_policy = _validate_document(wallet_policy)
        except (TypeError, KeyError, json.JSONDecodeError, BenchmarkPolicyValidationError, PolicyValidationError) as exc:
            raise PolicyIntegrityError("persisted run policy snapshot is invalid") from exc
        normalized = {
            "policyId": scenario_policy["policyId"],
            "revision": scenario_policy["revision"],
            "scenarioId": scenario_policy["scenarioId"],
            "subject": deepcopy(scenario_policy["subject"]),
            "scenarioPolicy": scenario_policy,
            "walletPolicy": wallet_policy,
        }
        if _document_digest(normalized) != row["policy_snapshot_digest"]:
            raise PolicyIntegrityError("persisted run policy snapshot integrity check failed")
        if (
            normalized["policyId"] != row["policy_id"]
            or normalized["scenarioId"] != row["scenario_id"]
            or normalized["subject"]["cardId"] != row["card_id"]
            or normalized["revision"] != row["policy_revision"]
        ):
            raise PolicyIntegrityError("persisted run policy snapshot binding is invalid")
        return normalized

    def _approved_events_locked(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT evaluation.event_json FROM policy_run_evaluations AS evaluation JOIN policy_run_decisions AS decision ON decision.run_id = evaluation.run_id AND decision.authorization_id = evaluation.authorization_id WHERE evaluation.run_id = ? AND decision.final_decision = 'approve'",
            (run_id,),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                event = json.loads(row["event_json"])
                authorization = event["authorization"]
                if not isinstance(event, dict) or not isinstance(authorization, dict):
                    raise TypeError("event is invalid")
            except (TypeError, KeyError, json.JSONDecodeError) as exc:
                raise PolicyIntegrityError("persisted approved event is invalid") from exc
            events.append(event)
        return sorted(
            events,
            key=lambda event: (
                str(event["authorization"].get("timestamp", "")),
                str(event["authorization"].get("authorization_id", "")),
            ),
        )

    def _approved_state_digest_locked(self, run_id: str) -> str:
        return _document_digest({"approvedEvents": self._approved_events_locked(run_id)})

    def start_run(self, scenario_id: str, card_id: str) -> dict[str, Any]:
        if not all(isinstance(value, str) and value for value in (scenario_id, card_id)):
            raise PolicyValidationError("scenario policy binding is invalid")
        scenario_policy = self.get_scenario_policy(scenario_id, card_id)
        wallet_policy = self._wallet_policy_for_card_or_none(card_id)
        snapshot = {
            "policyId": scenario_policy["policyId"],
            "revision": scenario_policy["revision"],
            "scenarioId": scenario_policy["scenarioId"],
            "subject": deepcopy(scenario_policy["subject"]),
            "scenarioPolicy": scenario_policy,
            "walletPolicy": wallet_policy,
        }
        serialized = _canonical_document(snapshot)
        digest = _document_digest(snapshot)
        with self._lock:
            for _ in range(5):
                run_id = token_urlsafe(24)
                try:
                    self._connection.execute("BEGIN IMMEDIATE")
                    self._connection.execute(
                        "INSERT INTO policy_runs(run_id, policy_id, scenario_id, card_id, policy_revision, policy_snapshot_json, policy_snapshot_digest, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            run_id,
                            snapshot["policyId"],
                            snapshot["scenarioId"],
                            snapshot["subject"]["cardId"],
                            snapshot["revision"],
                            serialized,
                            digest,
                            _iso_now(),
                        ),
                    )
                    self._connection.execute("COMMIT")
                    self._lock_database_files()
                    return {"runId": run_id, "policySnapshot": deepcopy(snapshot)}
                except sqlite3.IntegrityError:
                    self._connection.execute("ROLLBACK")
            raise PolicyConflictError("could not allocate a run identifier")

    def evaluate_run_event(
        self,
        run_id: str,
        event: Mapping[str, Any],
        evaluator: Callable[[Mapping[str, Any], Mapping[str, Any] | None, list[Mapping[str, Any]]], Mapping[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(event, Mapping):
            raise PolicyValidationError("event is invalid")
        serialized_event = _canonical_document(event)
        event_digest = _document_digest(event)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                run = self._run_row_for(run_id)
                snapshot = self._decode_run_snapshot(run)
                try:
                    validate_event_binding(snapshot["scenarioPolicy"], event)
                    authorization_id = event["authorization"]["authorization_id"]
                except (BenchmarkPolicyValidationError, KeyError, TypeError) as exc:
                    raise PolicyValidationError("event does not match the run policy binding") from exc
                if not isinstance(authorization_id, str) or not authorization_id:
                    raise PolicyValidationError("authorization ID is invalid")
                existing = self._connection.execute(
                    "SELECT evaluation_json, event_digest, approved_state_digest FROM policy_run_evaluations WHERE run_id = ? AND authorization_id = ?",
                    (run_id, authorization_id),
                ).fetchone()
                current_state_digest = self._approved_state_digest_locked(run_id)
                if existing is not None:
                    if existing["event_digest"] != event_digest:
                        raise PolicyConflictError("authorization event conflict")
                    decision = self._connection.execute(
                        "SELECT final_decision FROM policy_run_decisions WHERE run_id = ? AND authorization_id = ?",
                        (run_id, authorization_id),
                    ).fetchone()
                    if decision is not None or existing["approved_state_digest"] == current_state_digest:
                        try:
                            evaluation = json.loads(existing["evaluation_json"])
                        except json.JSONDecodeError as exc:
                            raise PolicyIntegrityError("persisted evaluation is invalid") from exc
                        self._connection.execute("COMMIT")
                        return evaluation, snapshot
                    self._connection.execute(
                        "DELETE FROM policy_run_evaluations WHERE run_id = ? AND authorization_id = ?",
                        (run_id, authorization_id),
                    )
                prior_approved_events = self._approved_events_locked(run_id)
                evaluation = dict(
                    evaluator(
                        snapshot["scenarioPolicy"],
                        snapshot["walletPolicy"],
                        prior_approved_events,
                    )
                )
                if evaluation.get("authorization_id") != authorization_id or evaluation.get("recommended_decision") not in {
                    "approve", "decline", "step_up"
                }:
                    raise PolicyIntegrityError("rule evaluator returned an invalid result")
                self._connection.execute(
                    "INSERT INTO policy_run_evaluations(run_id, authorization_id, event_digest, event_json, evaluation_json, approved_state_digest, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        authorization_id,
                        event_digest,
                        serialized_event,
                        _canonical_document(evaluation),
                        current_state_digest,
                        _iso_now(),
                    ),
                )
                self._connection.execute("COMMIT")
                self._lock_database_files()
                return evaluation, snapshot
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def record_run_decision(
        self,
        run_id: str,
        authorization_id: str,
        decision: str,
        customer_confirmed: bool = False,
    ) -> dict[str, Any]:
        if (
            not isinstance(authorization_id, str)
            or not authorization_id
            or decision not in {"approve", "decline", "step_up"}
            or not isinstance(customer_confirmed, bool)
        ):
            raise PolicyValidationError("run decision is invalid")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._run_row_for(run_id)
                evaluation_row = self._connection.execute(
                    "SELECT evaluation_json, approved_state_digest FROM policy_run_evaluations WHERE run_id = ? AND authorization_id = ?",
                    (run_id, authorization_id),
                ).fetchone()
                if evaluation_row is None:
                    raise PolicyValidationError("authorization has not been evaluated")
                try:
                    evaluation = json.loads(evaluation_row["evaluation_json"])
                    expected = evaluation["recommended_decision"]
                except (KeyError, TypeError, json.JSONDecodeError) as exc:
                    raise PolicyIntegrityError("persisted evaluation is invalid") from exc
                if evaluation_row["approved_state_digest"] != self._approved_state_digest_locked(run_id):
                    raise PolicyConflictError("evaluation state changed; evaluate again")
                existing = self._connection.execute(
                    "SELECT submitted_decision, final_decision FROM policy_run_decisions WHERE run_id = ? AND authorization_id = ?",
                    (run_id, authorization_id),
                ).fetchone()
                if existing is not None:
                    if existing["final_decision"] is not None:
                        if existing["final_decision"] != decision:
                            raise PolicyConflictError("run decision conflict")
                        self._connection.execute("COMMIT")
                        return {
                            "runId": run_id,
                            "authorizationId": authorization_id,
                            "status": "already_recorded",
                            "decision": decision,
                        }
                    if existing["submitted_decision"] != "step_up":
                        raise PolicyIntegrityError("persisted run decision is invalid")
                    if decision == "step_up":
                        self._connection.execute("COMMIT")
                        return {
                            "runId": run_id,
                            "authorizationId": authorization_id,
                            "status": "step_up_recorded",
                            "decision": "step_up",
                        }
                    if decision == "approve" and not customer_confirmed:
                        raise PolicyValidationError("customer confirmation is required to approve a stepped-up decision")
                    self._connection.execute(
                        "UPDATE policy_run_decisions SET final_decision = ?, customer_confirmed = ?, committed_at = ? WHERE run_id = ? AND authorization_id = ?",
                        (decision, int(customer_confirmed), _iso_now(), run_id, authorization_id),
                    )
                    self._connection.execute("COMMIT")
                    self._lock_database_files()
                    return {
                        "runId": run_id,
                        "authorizationId": authorization_id,
                        "status": "resolved",
                        "decision": decision,
                    }
                if expected == "step_up":
                    if decision != "step_up" or customer_confirmed:
                        raise PolicyValidationError("a stepped-up decision must be recorded before resolution")
                    final_decision = None
                elif decision != expected or customer_confirmed:
                    raise PolicyValidationError("decision does not match policy evaluation")
                else:
                    final_decision = decision
                self._connection.execute(
                    "INSERT INTO policy_run_decisions(run_id, authorization_id, submitted_decision, final_decision, customer_confirmed, committed_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        authorization_id,
                        decision,
                        final_decision,
                        int(customer_confirmed),
                        _iso_now(),
                    ),
                )
                self._connection.execute("COMMIT")
                self._lock_database_files()
                return {
                    "runId": run_id,
                    "authorizationId": authorization_id,
                    "status": "step_up_recorded" if final_decision is None else "recorded",
                    "decision": decision,
                }
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def get_run_status(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._run_row_for(run_id)
            snapshot = self._decode_run_snapshot(run)
            rows = self._connection.execute(
                "SELECT evaluation.authorization_id, decision.submitted_decision, decision.final_decision FROM policy_run_evaluations AS evaluation LEFT JOIN policy_run_decisions AS decision ON decision.run_id = evaluation.run_id AND decision.authorization_id = evaluation.authorization_id WHERE evaluation.run_id = ? ORDER BY evaluation.authorization_id",
                (run_id,),
            ).fetchall()
        decisions = [
            {
                "authorizationId": row["authorization_id"],
                "submittedDecision": row["submitted_decision"],
                "finalDecision": row["final_decision"],
            }
            for row in rows
        ]
        finalized = [entry for entry in decisions if entry["finalDecision"] is not None]
        return {
            "runId": run_id,
            "policyId": snapshot["policyId"],
            "policyRevision": snapshot["revision"],
            "scenarioId": snapshot["scenarioId"],
            "cardId": snapshot["subject"]["cardId"],
            "evaluatedAuthorizationCount": len(decisions),
            "finalizedAuthorizationCount": len(finalized),
            "approvedCount": sum(entry["finalDecision"] == "approve" for entry in finalized),
            "declinedCount": sum(entry["finalDecision"] == "decline" for entry in finalized),
            "stepUpPendingCount": sum(
                entry["submittedDecision"] == "step_up" and entry["finalDecision"] is None
                for entry in decisions
            ),
            "decisions": decisions,
        }

    def _decode_row(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            document = json.loads(row["document_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise PolicyIntegrityError("persisted policy is not valid JSON") from exc
        try:
            validated = _validate_document(document)
        except PolicyValidationError as exc:
            raise PolicyIntegrityError("persisted policy validation failed") from exc
        if _document_digest(validated) != row["document_digest"]:
            raise PolicyIntegrityError("persisted policy integrity check failed")
        if (validated["policyId"] != row["policy_id"]
                or validated["revision"] != row["revision"]
                or validated["subject"]["cardId"] != row["card_id"]):
            raise PolicyIntegrityError("persisted policy identity check failed")
        return validated

    def _verify_revision_chain(self, current: sqlite3.Row, document: Mapping[str, Any]) -> None:
        rows = self._connection.execute(
            "SELECT revision, document_json, document_digest, previous_digest FROM policy_revisions WHERE policy_id = ? ORDER BY revision",
            (document["policyId"],),
        ).fetchall()
        previous_digest: str | None = None
        for expected_revision, row in enumerate(rows, start=1):
            if row["revision"] != expected_revision or row["previous_digest"] != previous_digest:
                raise PolicyIntegrityError("persisted policy revision chain is invalid")
            try:
                revision_document = _validate_document(json.loads(row["document_json"]))
            except (TypeError, json.JSONDecodeError, PolicyValidationError) as exc:
                raise PolicyIntegrityError("persisted policy revision is invalid") from exc
            if (revision_document["policyId"] != document["policyId"]
                    or revision_document["revision"] != expected_revision
                    or _document_digest(revision_document) != row["document_digest"]):
                raise PolicyIntegrityError("persisted policy revision integrity check failed")
            previous_digest = row["document_digest"]
        if (not rows or document["revision"] != len(rows)
                or current["document_digest"] != previous_digest):
            raise PolicyIntegrityError("persisted policy revision chain is incomplete")

    def _row_for(self, policy_id: str | None = None, card_id: str | None = None) -> sqlite3.Row:
        if policy_id is not None:
            row = self._connection.execute(
                "SELECT * FROM policies WHERE policy_id = ?", (policy_id,)
            ).fetchone()
        elif card_id is not None:
            row = self._connection.execute(
                "SELECT * FROM policies WHERE card_id = ?", (card_id,)
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT * FROM policies ORDER BY policy_id LIMIT 1"
            ).fetchone()
        if row is None:
            raise PolicyValidationError("policy not found")
        return row

    def get(self, policy_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            row = self._row_for(policy_id=policy_id)
            document = self._decode_row(row)
            self._verify_revision_chain(row, document)
            return document

    def get_for_card(self, card_id: str) -> dict[str, Any]:
        if not isinstance(card_id, str) or not card_id:
            raise PolicyValidationError("cardId is invalid")
        with self._lock:
            row = self._row_for(card_id=card_id)
            document = self._decode_row(row)
            self._verify_revision_chain(row, document)
            return document

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM policies ORDER BY policy_id"
            ).fetchall()
            documents = []
            for row in rows:
                document = self._decode_row(row)
                self._verify_revision_chain(row, document)
                documents.append(document)
            return documents

    def create(self, document: Any) -> dict[str, Any]:
        stored = _validate_document(document)
        if stored["revision"] != 1:
            raise PolicyValidationError("new policy revision must be 1")
        stored = {
            **stored,
            "updatedAt": _iso_now(),
            "updatedBy": "policy-api",
        }
        serialized = _canonical_document(stored)
        digest = _document_digest(stored)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "INSERT INTO policies(policy_id, card_id, revision, document_json, document_digest, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (stored["policyId"], stored["subject"]["cardId"], stored["revision"], serialized,
                     digest, stored["updatedAt"], stored["updatedBy"]),
                )
                self._connection.execute(
                    "INSERT INTO policy_revisions(policy_id, revision, document_json, document_digest, previous_digest, changed_at, changed_by) VALUES (?, ?, ?, ?, NULL, ?, ?)",
                    (stored["policyId"], stored["revision"], serialized, digest,
                     stored["updatedAt"], stored["updatedBy"]),
                )
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._connection.execute("ROLLBACK")
                raise PolicyConflictError("policy already exists for this policy or card") from exc
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            self._lock_database_files()
        return deepcopy(stored)

    def update(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise PolicyValidationError("policy update must be an object")
        if set(request) != {"policyId", "expectedRevision", "patch"}:
            raise PolicyValidationError("policy update fields are invalid")
        revision = request["expectedRevision"]
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise PolicyValidationError("expectedRevision must be an integer")
        patch = validate_policy_patch(request["patch"])
        policy_id = request["policyId"]
        if not isinstance(policy_id, str) or not policy_id:
            raise PolicyValidationError("policy not found")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                previous = self._decode_row(self._row_for(policy_id=policy_id))
                self._verify_revision_chain(self._row_for(policy_id=policy_id), previous)
                if revision != previous["revision"]:
                    raise PolicyConflictError("policy revision conflict")
                stored = {
                    **previous,
                    **deepcopy(patch),
                    "revision": previous["revision"] + 1,
                    "updatedAt": _iso_now(),
                    "updatedBy": "customer",
                }
                serialized = _canonical_document(stored)
                digest = _document_digest(stored)
                cursor = self._connection.execute(
                    "UPDATE policies SET revision = ?, document_json = ?, document_digest = ?, updated_at = ?, updated_by = ? WHERE policy_id = ? AND revision = ?",
                    (stored["revision"], serialized, digest, stored["updatedAt"], stored["updatedBy"],
                     policy_id, revision),
                )
                if cursor.rowcount != 1:
                    raise PolicyConflictError("policy revision conflict")
                self._connection.execute(
                    "INSERT INTO policy_revisions(policy_id, revision, document_json, document_digest, previous_digest, changed_at, changed_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (policy_id, stored["revision"], serialized, digest,
                     _document_digest(previous), stored["updatedAt"], stored["updatedBy"]),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            self._lock_database_files()
        return deepcopy(stored)

    def revisions(self, policy_id: str) -> list[dict[str, Any]]:
        with self._lock:
            current = self._row_for(policy_id=policy_id)
            self._verify_revision_chain(current, self._decode_row(current))
            rows = self._connection.execute(
                "SELECT revision, document_digest, previous_digest, changed_at, changed_by FROM policy_revisions WHERE policy_id = ? ORDER BY revision",
                (policy_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _event_date(event: Mapping[str, Any]) -> str | None:
    try:
        timestamp = str(event["authorization"]["timestamp"])
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def _policy_categories(items: list[Mapping[str, Any]]) -> set[str]:
    return {str(item.get("item_category")) for item in items if item.get("item_category")}


def _profile_for_categories(categories: set[str]) -> str | None:
    for name, dataset_categories in CATEGORY_TO_DATASET.items():
        if categories and categories.issubset(dataset_categories):
            return name
    return None


def evaluate_wallet_policy(
    event: Mapping[str, Any], history: Any, document: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Evaluate the active customer policy using only trusted event/history facts.

    A confirmed mandate is evaluated elsewhere by ``rulebook.evaluate_request``.
    These checks are additive: a dynamic-policy failure can only tighten the
    result, and an unavailable material fact becomes a review rather than an
    implicit approval.
    """

    try:
        # Validation is intentionally re-run at the execution boundary.  A
        # malformed or tampered persisted document must not grant permission.
        validated_patch = validate_policy_patch({
            key: document[key]
            for key in (
                "enabled",
                "dailySpendingLimitChf",
                "adaptiveSpendProfiles",
                "reviewTriggers",
                "assistantAuthority",
            )
        })
    except (KeyError, PolicyValidationError):
        return [{
            "name": "Dynamic wallet policy",
            "outcome": "review",
            "reason_code": "policy_configuration_invalid",
            "detail": "The active dynamic policy could not be verified, so this purchase needs review.",
        }]

    authorization = event.get("authorization")
    if not isinstance(authorization, Mapping):
        return [{
            "name": "Dynamic wallet policy",
            "outcome": "review",
            "reason_code": "authorization_missing",
            "detail": "The purchase facts required by the dynamic policy are missing.",
        }]

    checks: list[dict[str, Any]] = []

    def add(name: str, outcome: str, reason_code: str, detail: str) -> None:
        checks.append({
            "name": name,
            "outcome": outcome,
            "reason_code": reason_code,
            "detail": detail,
        })

    if not validated_patch["enabled"]:
        add(
            "Dynamic wallet policy",
            "pass",
            "dynamic_policy_disabled",
            "The optional dynamic policy is disabled; the confirmed mandate still applies.",
        )
        return checks

    try:
        amount = _money(authorization["billing_amount_chf"], "authorization.billing_amount_chf")
        card_id = authorization["card_id"]
        if not isinstance(card_id, str) or not card_id:
            raise PolicyValidationError("authorization.card_id is invalid")
    except (KeyError, PolicyValidationError):
        add(
            "Daily spending limit",
            "review",
            "daily_limit_unverifiable",
            "The amount or card identifier needed for the daily limit is unavailable.",
        )
        return checks

    date = _event_date(event)
    if date is None:
        add(
            "Daily spending limit",
            "review",
            "purchase_date_unavailable",
            "The purchase timestamp needed for the daily spending limit is unavailable.",
        )
    else:
        spent = Decimal(history.approved_spend_on(card_id, date))
        limit = _money(validated_patch["dailySpendingLimitChf"], "dailySpendingLimitChf")
        projected = spent + amount
        if projected > limit:
            add(
                "Daily spending limit",
                "fail",
                "daily_spending_limit_exceeded",
                f"CHF {projected:.2f} would exceed the CHF {limit:.2f} daily limit (CHF {spent:.2f} completed today).",
            )
        else:
            add(
                "Daily spending limit",
                "pass",
                "daily_spending_within_limit",
                f"CHF {projected:.2f} stays within the CHF {limit:.2f} daily limit.",
            )

    items_value = authorization.get("items")
    items = [item for item in items_value if isinstance(item, Mapping)] if isinstance(items_value, list) else []
    categories = _policy_categories(items)
    profile_name = _profile_for_categories(categories)
    if not items or len(items) != len(items_value or []):
        add(
            "Category maximum",
            "review",
            "basket_categories_unavailable",
            "The item categories needed for the adaptive limit are unavailable.",
        )
    elif profile_name is None:
        add(
            "Category maximum",
            "pass",
            "category_limit_not_configured",
            "No adaptive maximum is configured for this basket category.",
        )
    else:
        category_limit = _money(
            validated_patch["adaptiveSpendProfiles"][profile_name]["maximumChf"],
            f"{profile_name} maximumChf",
        )
        if amount > category_limit:
            add(
                "Category maximum",
                "fail",
                "category_limit_exceeded",
                f"CHF {amount:.2f} is above the CHF {category_limit:.2f} {profile_name.lower()} maximum.",
            )
        else:
            add(
                "Category maximum",
                "pass",
                "category_limit_within_limit",
                f"CHF {amount:.2f} is within the CHF {category_limit:.2f} {profile_name.lower()} maximum.",
            )

    merchant = authorization.get("merchant")
    merchant_id = merchant.get("merchant_id") if isinstance(merchant, Mapping) else None
    familiarity: int | None = None
    if isinstance(merchant_id, str) and merchant_id:
        familiarity = int(history.approved[card_id, merchant_id])

    triggers = set(validated_patch["reviewTriggers"])
    if "new_merchant" in triggers:
        if familiarity is None:
            add(
                "New merchant review",
                "review",
                "merchant_familiarity_unavailable",
                "The merchant identifier needed to check your first-purchase preference is unavailable.",
            )
        elif familiarity == 0:
            add(
                "New merchant review",
                "review",
                "new_merchant_confirmation_required",
                "This is a new merchant for this card, and your policy asks before a first purchase.",
            )
        else:
            add(
                "New merchant review",
                "pass",
                "merchant_seen_before",
                f"This card has {familiarity} prior approved purchases with this merchant.",
            )

    if "online_purchase" in triggers:
        channel = authorization.get("channel")
        if channel in {"ecommerce", "recurring"}:
            add(
                "Online purchase review",
                "review",
                "online_purchase_confirmation_required",
                "Your policy asks you to confirm card-not-present purchases.",
            )
        elif isinstance(channel, str) and channel:
            add(
                "Online purchase review",
                "pass",
                "online_purchase_not_applicable",
                "This purchase is not on a card-not-present channel.",
            )
        else:
            add(
                "Online purchase review",
                "review",
                "purchase_channel_unavailable",
                "The purchase channel needed for your online-purchase preference is unavailable.",
            )

    if "unusual_activity" in triggers:
        recent = authorization.get("recent_attempt_count_10m")
        device_id = authorization.get("customer_device_id")
        if not isinstance(recent, int) or isinstance(recent, bool) or recent < 0:
            add(
                "Unusual activity review",
                "review",
                "attempt_context_unavailable",
                "The recent-attempt signal needed for your unusual-activity preference is unavailable.",
            )
        elif recent >= 3:
            add(
                "Unusual activity review",
                "review",
                "unusual_attempt_velocity",
                f"There were {recent} earlier attempts in ten minutes, so your policy asks for confirmation.",
            )
        elif isinstance(device_id, str) and device_id and history.approved_device_count(card_id, device_id) == 0:
            add(
                "Unusual activity review",
                "review",
                "unfamiliar_device_confirmation_required",
                "This device has no prior approved purchases for this card, so your policy asks for confirmation.",
            )
        else:
            add(
                "Unusual activity review",
                "pass",
                "activity_within_expected_pattern",
                "The recent-attempt and device signals match this card's known activity.",
            )

    authority = validated_patch["assistantAuthority"]
    if authority == "review":
        add(
            "Assistant approval access",
            "review",
            "customer_review_required",
            "Your approval-access setting asks you before every purchase.",
        )
    elif authority == "trusted" and familiarity == 0:
        add(
            "Assistant approval access",
            "review",
            "trusted_merchant_required",
            "Your assistant may approve trusted purchases only; this merchant is new to this card.",
        )
    else:
        description = "Your assistant may approve a purchase that passes every active rule."
        if authority == "trusted":
            description = "This familiar purchase can be approved automatically after every active rule passes."
        add("Assistant approval access", "pass", "assistant_authorized", description)

    return checks
