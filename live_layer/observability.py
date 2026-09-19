from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import math
import re
from secrets import token_bytes
from threading import RLock
from time import perf_counter_ns
from typing import Any, Iterator, Mapping
from uuid import uuid4


DEFAULT_EVENT_NAMES = frozenset({
    "decision.request_received",
    "decision.schema_validated",
    "decision.context_resolved",
    "decision.evaluated",
    "decision.recorded",
    "decision.step_up",
    "decision.resolved",
    "decision.fallback",
    "decision.error",
    "decision.deadline_missed",
    "graph.projection_completed",
    "graph.projection_failed",
})

DEFAULT_SPAN_NAMES = frozenset({
    "decision.request",
    "decision.validate",
    "decision.context",
    "decision.evaluate",
    "decision.record",
    "decision.resolve",
})

DEFAULT_REASON_CODES = frozenset({
    "activity_within_expected_pattern",
    "assistant_authorized",
    "attempt_velocity_high",
    "attempt_velocity_normal",
    "attempt_context_unavailable",
    "authorization_missing",
    "basket_categories_unavailable",
    "basket_matches_instruction",
    "basket_outside_instruction",
    "buyer_authorized",
    "buyer_or_mandate_inactive",
    "category_limit_exceeded",
    "category_limit_not_configured",
    "category_limit_within_limit",
    "customer_review_required",
    "currency_needs_review",
    "customer_confirmation",
    "daily_limit_unverifiable",
    "daily_spending_limit_exceeded",
    "daily_spending_within_limit",
    "dynamic_policy_disabled",
    "merchant_catalogue_match",
    "merchant_familiarity_unavailable",
    "merchant_identity_mismatch",
    "merchant_not_in_catalogue",
    "merchant_unfamiliar_to_card",
    "merchant_seen_before",
    "new_merchant_confirmation_required",
    "online_purchase_confirmation_required",
    "online_purchase_not_applicable",
    "order_total_mismatch",
    "order_total_unverifiable",
    "order_total_verified",
    "period_limit_exceeded",
    "period_spend_unavailable",
    "period_within_limit",
    "policy_configuration_invalid",
    "purchase_channel_unavailable",
    "purchase_date_unavailable",
    "purchase_limit_exceeded",
    "purchase_limit_unavailable",
    "purchase_within_limit",
    "recent_attempt_count_invalid",
    "trusted_merchant_required",
    "unfamiliar_device_confirmation_required",
    "unrecognized_reason_code",
    "unusual_attempt_velocity",
})

DEFAULT_FALLBACK_REASONS = frozenset({
    "context_unavailable",
    "deadline_guard",
    "graph_unavailable",
    "invalid_dependency_response",
    "model_unavailable",
    "storage_unavailable",
    "unrecognized_fallback",
})

DEFAULT_ERROR_CLASSES = frozenset({
    "conflict_error",
    "context_error",
    "deadline_exceeded",
    "dependency_error",
    "internal_error",
    "permission_error",
    "validation_error",
})

CONTROLLED_LABEL_VALUES: dict[str, frozenset[object]] = {
    "component": frozenset({"guardian", "mock_api", "receipt_store", "rulebook", "viseca_mock"}),
    "dependency": frozenset({"context", "graph", "model", "storage", "viseca"}),
    "outcome": frozenset({"approve", "decline", "step_up"}),
    "status": frozenset({
        "error",
        "idempotent_replay",
        "ok",
        "recorded",
        "received",
        "resolved",
        "validated",
    }),
    "fallback": frozenset({False, True}),
}

_OUTCOMES = frozenset({"approve", "decline", "step_up"})
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TRACE_PATTERN = re.compile(r"^trace_[0-9a-f]{32}$")
_PSEUDONYM_PATTERN = re.compile(r"^hmac_[a-z0-9_]{1,32}_[0-9a-f]{64}$")
_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_PSEUDONYMIZED_ATTRIBUTES = frozenset({
    "authorization_id",
    "card_id",
    "correlation_id",
    "customer_device_id",
    "customer_id",
    "event_id",
    "item_id",
    "mandate_id",
    "merchant_id",
    "product_id",
    "profile_id",
    "request_id",
    "run_id",
    "trace_id",
})
_SAFE_TEXT_ATTRIBUTES = frozenset({"engine_version", "policy_version", "schema_version"})
_SAFE_HASH_ATTRIBUTES = frozenset({"policy_hash", "receipt_hash", "request_hash"})
_SAFE_NUMBER_ATTRIBUTES = frozenset({
    "attempt_count",
    "check_count",
    "context_age_ms",
    "deadline_headroom_ms",
    "deadline_ms",
    "queue_latency_ms",
})
_SAFE_BOOLEAN_ATTRIBUTES = frozenset({
    "context_fresh",
    "deadline_missed",
    "dependency_available",
    "duplicate",
    "idempotent",
    "receipt_complete",
})
_SAFE_ENUM_ATTRIBUTES = frozenset({"error_class", "fallback_reason", "idempotency_result", "receipt_status"})
_IDEMPOTENCY_RESULTS = frozenset({"already_recorded", "conflict", "recorded"})
_RECEIPT_STATUSES = frozenset({"complete", "incomplete", "missing"})
_SENSITIVE_NAME_PARTS = frozenset({
    "account",
    "address",
    "api",
    "authorization",
    "body",
    "card",
    "credential",
    "customer",
    "description",
    "email",
    "instruction",
    "item",
    "key",
    "merchant",
    "message",
    "name",
    "pan",
    "password",
    "payload",
    "phone",
    "product",
    "prompt",
    "raw",
    "secret",
    "text",
    "token",
})


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    correlation_id: str | None = None


class Telemetry:
    def __init__(
        self,
        *,
        max_events: int = 512,
        max_spans: int = 512,
        max_duration_samples: int = 1024,
        secret: bytes | str | None = None,
        event_names: frozenset[str] | set[str] | tuple[str, ...] = DEFAULT_EVENT_NAMES,
        span_names: frozenset[str] | set[str] | tuple[str, ...] = DEFAULT_SPAN_NAMES,
        reason_codes: frozenset[str] | set[str] | tuple[str, ...] = DEFAULT_REASON_CODES,
    ):
        self._validate_capacity(max_events, "max_events")
        self._validate_capacity(max_spans, "max_spans")
        self._validate_capacity(max_duration_samples, "max_duration_samples")
        self._event_names = self._validate_names(event_names, "event")
        self._span_names = self._validate_names(span_names, "span")
        self._reason_codes = self._validate_codes(reason_codes, "reason")
        self._duration_buckets = frozenset({"decision", *self._span_names})
        if secret is None:
            self._secret = token_bytes(32)
        elif isinstance(secret, str):
            self._secret = secret.encode("utf-8")
        elif isinstance(secret, bytes):
            self._secret = secret
        else:
            raise TypeError("secret must be bytes, str, or None")
        if not self._secret:
            raise ValueError("secret must not be empty")
        self._max_events = max_events
        self._max_spans = max_spans
        self._max_duration_samples = max_duration_samples
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._spans: deque[dict[str, Any]] = deque(maxlen=max_spans)
        self._events_total: Counter[str] = Counter()
        self._spans_total: Counter[str] = Counter()
        self._outcomes_total: Counter[str] = Counter()
        self._reason_codes_total: Counter[str] = Counter()
        self._errors_total: Counter[str] = Counter()
        self._fallbacks_total: Counter[str] = Counter()
        self._duration_counts: Counter[str] = Counter()
        self._duration_totals: Counter[str] = Counter()
        self._duration_mins: dict[str, float] = {}
        self._duration_maxs: dict[str, float] = {}
        self._duration_samples: dict[str, deque[float]] = {
            bucket: deque(maxlen=max_duration_samples) for bucket in self._duration_buckets
        }
        self._duration_samples_dropped: Counter[str] = Counter()
        self._events_dropped = 0
        self._spans_dropped = 0
        self._attributes_redacted = 0
        self._lock = RLock()
        self._active_trace: ContextVar[TraceContext | None] = ContextVar(
            f"telemetry_trace_{id(self)}", default=None
        )

    @contextmanager
    def trace(self, correlation_id: object | None = None) -> Iterator[TraceContext]:
        context = self.start_trace(correlation_id)
        token = self._active_trace.set(context)
        try:
            yield context
        finally:
            self._active_trace.reset(token)

    def start_trace(self, correlation_id: object | None = None) -> TraceContext:
        return TraceContext(
            trace_id=f"trace_{uuid4().hex}",
            correlation_id=self._normalise_correlation_id(correlation_id),
        )

    def pseudonymize(self, value: object, namespace: str = "identifier") -> str:
        if not isinstance(namespace, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", namespace):
            raise ValueError("namespace must be a controlled identifier")
        raw_value = self._stable_value(value)
        digest = hmac.new(
            self._secret,
            namespace.encode("ascii") + b":" + raw_value,
            sha256,
        ).hexdigest()
        return f"hmac_{namespace}_{digest}"

    def event(
        self,
        name: str,
        *,
        trace: TraceContext | None = None,
        trace_id: object | None = None,
        correlation_id: object | None = None,
        labels: Mapping[str, object] | None = None,
        attributes: Mapping[object, object] | None = None,
    ) -> dict[str, Any]:
        self._validate_event_name(name)
        context = self._resolve_trace(trace, trace_id, correlation_id)
        cleaned_labels = self._validate_labels(labels)
        cleaned_attributes, redacted = self._sanitize_attributes(attributes)
        record = self._base_record(name, context, cleaned_labels, cleaned_attributes)
        self._store_event(record, redacted)
        return deepcopy(record)

    @contextmanager
    def span(
        self,
        name: str,
        *,
        trace: TraceContext | None = None,
        trace_id: object | None = None,
        correlation_id: object | None = None,
        labels: Mapping[str, object] | None = None,
        attributes: Mapping[object, object] | None = None,
    ) -> Iterator[TraceContext | None]:
        self._validate_span_name(name)
        context = self._resolve_trace(trace, trace_id, correlation_id)
        cleaned_labels = self._validate_labels(labels)
        cleaned_attributes, redacted = self._sanitize_attributes(attributes)
        started_at = self._timestamp()
        started_ns = perf_counter_ns()
        try:
            yield context
        except BaseException as error:
            duration_ms = (perf_counter_ns() - started_ns) / 1_000_000
            error_class = self._classify_error(error)
            self._store_span(
                name,
                context,
                cleaned_labels,
                cleaned_attributes,
                redacted,
                started_at,
                duration_ms,
                "error",
                error_class,
            )
            self._record_error_code(error_class, context, cleaned_labels, cleaned_attributes)
            raise
        else:
            duration_ms = (perf_counter_ns() - started_ns) / 1_000_000
            self._store_span(
                name,
                context,
                cleaned_labels,
                cleaned_attributes,
                redacted,
                started_at,
                duration_ms,
                "ok",
                None,
            )

    def record_decision(
        self,
        outcome: str,
        *,
        reason_codes: object = (),
        fallback: bool | str = False,
        duration_ms: float | int | None = None,
        trace: TraceContext | None = None,
        trace_id: object | None = None,
        correlation_id: object | None = None,
        labels: Mapping[str, object] | None = None,
        attributes: Mapping[object, object] | None = None,
    ) -> dict[str, Any]:
        if outcome not in _OUTCOMES:
            raise ValueError("outcome must be approve, decline, or step_up")
        context = self._resolve_trace(trace, trace_id, correlation_id)
        fallback_reason = self._normalise_fallback(fallback)
        merged_labels = self._merge_labels(labels, {"outcome": outcome, "fallback": bool(fallback_reason)})
        cleaned_labels = self._validate_labels(merged_labels)
        merged_attributes = dict(attributes or {})
        if fallback_reason:
            merged_attributes["fallback_reason"] = fallback_reason
        cleaned_attributes, redacted = self._sanitize_attributes(merged_attributes)
        normalized_reasons = self._normalise_reason_codes(reason_codes)
        if duration_ms is not None:
            self._validate_duration(duration_ms)
        record = self._base_record("decision.evaluated", context, cleaned_labels, cleaned_attributes)
        record["outcome"] = outcome
        record["reason_codes"] = normalized_reasons
        record["fallback"] = bool(fallback_reason)
        if duration_ms is not None:
            record["duration_ms"] = float(duration_ms)
        with self._lock:
            self._append_event(record)
            self._events_total[record["name"]] += 1
            self._attributes_redacted += redacted
            self._outcomes_total[outcome] += 1
            for code in set(normalized_reasons):
                self._reason_codes_total[code] += 1
            if fallback_reason:
                self._fallbacks_total[fallback_reason] += 1
            if duration_ms is not None:
                self._record_duration("decision", float(duration_ms))
        return deepcopy(record)

    def record_fallback(
        self,
        reason: str,
        *,
        trace: TraceContext | None = None,
        trace_id: object | None = None,
        correlation_id: object | None = None,
        labels: Mapping[str, object] | None = None,
        attributes: Mapping[object, object] | None = None,
    ) -> dict[str, Any]:
        fallback_reason = self._normalise_fallback(reason)
        if not fallback_reason:
            raise ValueError("fallback reason is required")
        merged_labels = self._merge_labels(labels, {"fallback": True})
        merged_attributes = dict(attributes or {})
        merged_attributes["fallback_reason"] = fallback_reason
        record = self.event(
            "decision.fallback",
            trace=trace,
            trace_id=trace_id,
            correlation_id=correlation_id,
            labels=merged_labels,
            attributes=merged_attributes,
        )
        with self._lock:
            self._fallbacks_total[fallback_reason] += 1
        return record

    def record_error(
        self,
        error: BaseException | str,
        *,
        trace: TraceContext | None = None,
        trace_id: object | None = None,
        correlation_id: object | None = None,
        labels: Mapping[str, object] | None = None,
        attributes: Mapping[object, object] | None = None,
    ) -> dict[str, Any]:
        error_class = self._classify_error(error)
        context = self._resolve_trace(trace, trace_id, correlation_id)
        cleaned_labels = self._validate_labels(self._merge_labels(labels, {"status": "error"}))
        merged_attributes = dict(attributes or {})
        merged_attributes["error_class"] = error_class
        cleaned_attributes, redacted = self._sanitize_attributes(merged_attributes)
        return self._record_error_code(error_class, context, cleaned_labels, cleaned_attributes, redacted)

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._metrics_snapshot_locked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "events": deepcopy(list(self._events)),
                "spans": deepcopy(list(self._spans)),
                "metrics": self._metrics_snapshot_locked(),
            }

    @staticmethod
    def _validate_capacity(value: int, field: str) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{field} must be a positive integer")

    @staticmethod
    def _validate_names(names: object, kind: str) -> frozenset[str]:
        if isinstance(names, str):
            raise TypeError(f"{kind} names must be an iterable of controlled names")
        try:
            result = frozenset(names)
        except TypeError as error:
            raise TypeError(f"{kind} names must be an iterable of controlled names") from error
        if not result or any(not isinstance(name, str) or not _NAME_PATTERN.fullmatch(name) for name in result):
            raise ValueError(f"{kind} names must be controlled dotted names")
        return result

    @staticmethod
    def _validate_codes(codes: object, kind: str) -> frozenset[str]:
        if isinstance(codes, str):
            raise TypeError(f"{kind} codes must be an iterable of controlled codes")
        try:
            result = frozenset(codes)
        except TypeError as error:
            raise TypeError(f"{kind} codes must be an iterable of controlled codes") from error
        if any(not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) for code in result):
            raise ValueError(f"{kind} codes must be controlled identifiers")
        return result

    def _validate_event_name(self, name: str) -> None:
        if not isinstance(name, str) or name not in self._event_names:
            raise ValueError("event name is not allowed")

    def _validate_span_name(self, name: str) -> None:
        if not isinstance(name, str) or name not in self._span_names:
            raise ValueError("span name is not allowed")

    def _resolve_trace(
        self,
        trace: TraceContext | None,
        trace_id: object | None,
        correlation_id: object | None,
    ) -> TraceContext | None:
        if trace is not None:
            if not isinstance(trace, TraceContext):
                raise TypeError("trace must be a TraceContext")
            if trace_id is not None or correlation_id is not None:
                raise ValueError("trace cannot be combined with trace_id or correlation_id")
            return TraceContext(
                self._normalise_trace_id(trace.trace_id),
                self._normalise_correlation_id(trace.correlation_id),
            )
        active = self._active_trace.get()
        if trace_id is None and correlation_id is None and active is not None:
            return active
        if trace_id is None and correlation_id is None:
            return None
        return TraceContext(
            self._normalise_trace_id(trace_id) if trace_id is not None else f"trace_{uuid4().hex}",
            self._normalise_correlation_id(correlation_id),
        )

    def _normalise_trace_id(self, value: object) -> str:
        if isinstance(value, str) and _TRACE_PATTERN.fullmatch(value):
            return value
        if isinstance(value, str) and _PSEUDONYM_PATTERN.fullmatch(value):
            return value
        return self.pseudonymize(value, "trace")

    def _normalise_correlation_id(self, value: object | None) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and _PSEUDONYM_PATTERN.fullmatch(value):
            return value
        return self.pseudonymize(value, "correlation")

    def _validate_labels(self, labels: Mapping[str, object] | None) -> dict[str, object]:
        if labels is None:
            return {}
        if not isinstance(labels, Mapping):
            raise TypeError("labels must be a mapping")
        result: dict[str, object] = {}
        for key, value in labels.items():
            if key not in CONTROLLED_LABEL_VALUES:
                raise ValueError("label name is not allowed")
            if not any(type(value) is type(candidate) and value == candidate for candidate in CONTROLLED_LABEL_VALUES[key]):
                raise ValueError("label value is not allowed")
            result[key] = value
        return {key: result[key] for key in sorted(result)}

    @staticmethod
    def _merge_labels(
        labels: Mapping[str, object] | None, additions: Mapping[str, object]
    ) -> dict[str, object]:
        merged = dict(labels or {})
        for key, value in additions.items():
            if key in merged and merged[key] != value:
                raise ValueError("controlled label conflicts with recorded value")
            merged[key] = value
        return merged

    def _sanitize_attributes(
        self, attributes: Mapping[object, object] | None
    ) -> tuple[dict[str, object], int]:
        if attributes is None:
            return {}, 0
        if not isinstance(attributes, Mapping):
            raise TypeError("attributes must be a mapping")
        result: dict[str, object] = {}
        redacted = 0
        for raw_key, value in attributes.items():
            if not isinstance(raw_key, str):
                redacted += 1
                continue
            key = self._canonical_key(raw_key)
            if not key:
                redacted += 1
            elif key in _PSEUDONYMIZED_ATTRIBUTES or key.endswith("_id") or key == "id":
                result[key] = self.pseudonymize(value, "identifier")
                redacted += 1
            elif self._is_sensitive_name(key):
                redacted += 1
            elif key in _SAFE_TEXT_ATTRIBUTES:
                if isinstance(value, str) and _TOKEN_PATTERN.fullmatch(value):
                    result[key] = value
                else:
                    redacted += 1
            elif key in _SAFE_HASH_ATTRIBUTES:
                result[key] = self.pseudonymize(value, "digest")
                redacted += 1
            elif key in _SAFE_NUMBER_ATTRIBUTES:
                if (isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(float(value)) and float(value) >= 0):
                    result[key] = float(value) if isinstance(value, float) else value
                else:
                    redacted += 1
            elif key in _SAFE_BOOLEAN_ATTRIBUTES:
                if isinstance(value, bool):
                    result[key] = value
                else:
                    redacted += 1
            elif key == "error_class":
                result[key] = self._classify_error(value if isinstance(value, str) else "internal_error")
            elif key == "fallback_reason":
                result[key] = self._normalise_fallback(value if isinstance(value, str) else "unrecognized_fallback")
            elif key == "idempotency_result":
                result[key] = value if isinstance(value, str) and value in _IDEMPOTENCY_RESULTS else "conflict"
            elif key == "receipt_status":
                result[key] = value if isinstance(value, str) and value in _RECEIPT_STATUSES else "missing"
            else:
                redacted += 1
        return {key: result[key] for key in sorted(result)}, redacted

    @staticmethod
    def _canonical_key(value: str) -> str:
        value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
        return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")

    @staticmethod
    def _is_sensitive_name(key: str) -> bool:
        return bool(set(key.split("_")) & _SENSITIVE_NAME_PARTS)

    @staticmethod
    def _stable_value(value: object) -> bytes:
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8", "surrogatepass")
        return repr(value).encode("utf-8", "backslashreplace")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _base_record(
        self,
        name: str,
        context: TraceContext | None,
        labels: Mapping[str, object],
        attributes: Mapping[str, object],
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "name": name,
            "occurred_at": self._timestamp(),
            "labels": dict(labels),
            "attributes": dict(attributes),
        }
        if context is not None:
            record["trace_id"] = context.trace_id
            if context.correlation_id is not None:
                record["correlation_id"] = context.correlation_id
        return record

    def _store_event(self, record: dict[str, Any], redacted: int) -> None:
        with self._lock:
            self._append_event(record)
            self._events_total[record["name"]] += 1
            self._attributes_redacted += redacted

    def _append_event(self, record: dict[str, Any]) -> None:
        if len(self._events) == self._max_events:
            self._events_dropped += 1
        self._events.append(record)

    def _store_span(
        self,
        name: str,
        context: TraceContext | None,
        labels: Mapping[str, object],
        attributes: Mapping[str, object],
        redacted: int,
        started_at: str,
        duration_ms: float,
        status: str,
        error_class: str | None,
    ) -> None:
        record = self._base_record(name, context, labels, attributes)
        record["started_at"] = started_at
        record["duration_ms"] = duration_ms
        record["status"] = status
        if error_class is not None:
            record["error_class"] = error_class
        with self._lock:
            if len(self._spans) == self._max_spans:
                self._spans_dropped += 1
            self._spans.append(record)
            self._spans_total[name] += 1
            self._attributes_redacted += redacted
            self._record_duration(name, duration_ms)

    def _record_error_code(
        self,
        error_class: str,
        context: TraceContext | None,
        labels: Mapping[str, object],
        attributes: Mapping[str, object] | None = None,
        redacted: int = 0,
    ) -> dict[str, Any]:
        error_labels = dict(labels)
        error_labels["status"] = "error"
        error_attributes = dict(attributes or {})
        error_attributes["error_class"] = error_class
        record = self._base_record("decision.error", context, error_labels, error_attributes)
        with self._lock:
            self._append_event(record)
            self._events_total["decision.error"] += 1
            self._errors_total[error_class] += 1
            self._attributes_redacted += redacted
        return deepcopy(record)

    def _normalise_reason_codes(self, reason_codes: object) -> list[str]:
        if isinstance(reason_codes, str):
            raise TypeError("reason_codes must be an iterable of controlled codes")
        try:
            values = list(reason_codes)
        except TypeError as error:
            raise TypeError("reason_codes must be an iterable of controlled codes") from error
        return [code if isinstance(code, str) and code in self._reason_codes else "unrecognized_reason_code" for code in values]

    def _normalise_fallback(self, fallback: bool | str) -> str | None:
        if fallback is False:
            return None
        if fallback is True:
            return "unrecognized_fallback"
        if isinstance(fallback, str):
            return fallback if fallback in DEFAULT_FALLBACK_REASONS else "unrecognized_fallback"
        raise TypeError("fallback must be a bool or controlled reason")

    @staticmethod
    def _validate_duration(value: float | int) -> None:
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(float(value)) or float(value) < 0):
            raise ValueError("duration_ms must be finite and non-negative")

    def _record_duration(self, bucket: str, duration_ms: float) -> None:
        self._duration_counts[bucket] += 1
        self._duration_totals[bucket] += duration_ms
        self._duration_mins[bucket] = min(duration_ms, self._duration_mins.get(bucket, duration_ms))
        self._duration_maxs[bucket] = max(duration_ms, self._duration_maxs.get(bucket, duration_ms))
        samples = self._duration_samples[bucket]
        if len(samples) == self._max_duration_samples:
            self._duration_samples_dropped[bucket] += 1
        samples.append(duration_ms)

    def _classify_error(self, error: BaseException | str) -> str:
        if isinstance(error, str):
            return error if error in DEFAULT_ERROR_CLASSES else "internal_error"
        if isinstance(error, TimeoutError):
            return "deadline_exceeded"
        if isinstance(error, PermissionError):
            return "permission_error"
        if isinstance(error, (ValueError, TypeError)):
            return "validation_error"
        if type(error).__name__ == "RequestError":
            return "validation_error"
        if isinstance(error, KeyError):
            return "context_error"
        if isinstance(error, OSError):
            return "dependency_error"
        return "internal_error"

    @staticmethod
    def _percentile(values: list[float], percentile: int) -> float:
        ordered = sorted(values)
        index = max(0, math.ceil((percentile / 100) * len(ordered)) - 1)
        return ordered[index]

    def _metrics_snapshot_locked(self) -> dict[str, Any]:
        durations: dict[str, dict[str, float | int]] = {}
        for bucket in sorted(self._duration_buckets):
            count = self._duration_counts[bucket]
            if not count:
                continue
            samples = list(self._duration_samples[bucket])
            durations[bucket] = {
                "count": count,
                "sample_count": len(samples),
                "samples_dropped": self._duration_samples_dropped[bucket],
                "total": self._duration_totals[bucket],
                "min": self._duration_mins[bucket],
                "max": self._duration_maxs[bucket],
                "p50": self._percentile(samples, 50),
                "p95": self._percentile(samples, 95),
                "p99": self._percentile(samples, 99),
            }
        return {
            "events_total": self._counter_snapshot(self._events_total),
            "spans_total": self._counter_snapshot(self._spans_total),
            "outcomes_total": self._counter_snapshot(self._outcomes_total),
            "reason_codes_total": self._counter_snapshot(self._reason_codes_total),
            "errors_total": self._counter_snapshot(self._errors_total),
            "fallbacks_total": self._counter_snapshot(self._fallbacks_total),
            "durations_ms": durations,
            "storage": {
                "events_retained": len(self._events),
                "events_dropped": self._events_dropped,
                "spans_retained": len(self._spans),
                "spans_dropped": self._spans_dropped,
                "attributes_redacted": self._attributes_redacted,
            },
        }

    @staticmethod
    def _counter_snapshot(counter: Counter[str]) -> dict[str, int]:
        return {key: counter[key] for key in sorted(counter)}
