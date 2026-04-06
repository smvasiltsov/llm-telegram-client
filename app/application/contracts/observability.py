from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from time import monotonic
from typing import Mapping, Protocol


_ALLOWED_LABEL_KEYS = (
    "operation",
    "result",
    "error_code",
    "transport",
    "mode",
    "runner",
    "method",
    "route",
    "status",
    "queue_name",
)
_SAFE_LABEL_PATTERN = re.compile(r"[^a-z0-9._-]+")
_MAX_LABEL_LEN = 64


@dataclass(frozen=True)
class ObservabilityContext:
    correlation_id: str
    request_id: str | None = None


@dataclass(frozen=True)
class MetricRecord:
    name: str
    value: float
    labels: Mapping[str, str]


class MetricsPort(Protocol):
    def increment(self, name: str, *, labels: Mapping[str, str] | None = None, value: int = 1) -> None: ...

    def observe_ms(self, name: str, *, value_ms: float, labels: Mapping[str, str] | None = None) -> None: ...

    def operation_timer(self, operation: str, *, transport: str) -> "OperationTimer": ...


def _normalize_label_value(value: str) -> str:
    normalized = _SAFE_LABEL_PATTERN.sub("_", str(value).lower()).strip("._-")
    if not normalized:
        return "unknown"
    return normalized[:_MAX_LABEL_LEN]


def sanitize_metric_labels(labels: Mapping[str, object] | None) -> dict[str, str]:
    if not labels:
        return {}
    safe: dict[str, str] = {}
    for key in _ALLOWED_LABEL_KEYS:
        if key not in labels:
            continue
        safe[key] = _normalize_label_value(str(labels[key]))
    return safe


def build_operation_labels(
    *,
    operation: str,
    transport: str,
    result: str | None = None,
    error_code: str | None = None,
    mode: str | None = None,
    runner: str | None = None,
) -> dict[str, str]:
    labels: dict[str, object] = {
        "operation": operation,
        "transport": transport,
    }
    if result is not None:
        labels["result"] = result
    if error_code is not None:
        labels["error_code"] = error_code
    if mode is not None:
        labels["mode"] = mode
    if runner is not None:
        labels["runner"] = runner
    return sanitize_metric_labels(labels)


class OperationTimer:
    def __init__(self, metrics: MetricsPort, *, operation: str, transport: str) -> None:
        self._metrics = metrics
        self._operation = operation
        self._transport = transport
        self._started = monotonic()

    def observe(self, *, result: str, error_code: str | None = None) -> float:
        elapsed_ms = max(0.0, (monotonic() - self._started) * 1000.0)
        self._metrics.observe_ms(
            "runtime_operation_latency_ms",
            value_ms=elapsed_ms,
            labels=build_operation_labels(
                operation=self._operation,
                transport=self._transport,
                result=result,
                error_code=error_code,
            ),
        )
        return elapsed_ms


class NoopMetricsPort:
    def increment(self, name: str, *, labels: Mapping[str, str] | None = None, value: int = 1) -> None:
        _ = (name, labels, value)

    def observe_ms(self, name: str, *, value_ms: float, labels: Mapping[str, str] | None = None) -> None:
        _ = (name, value_ms, labels)

    def operation_timer(self, operation: str, *, transport: str) -> OperationTimer:
        return OperationTimer(self, operation=operation, transport=transport)


class LoggingMetricsPort(NoopMetricsPort):
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("bot.metrics")

    def increment(self, name: str, *, labels: Mapping[str, str] | None = None, value: int = 1) -> None:
        record = MetricRecord(name=name, value=float(value), labels=sanitize_metric_labels(labels))
        self._logger.info("metric_increment name=%s value=%s labels=%s", record.name, int(record.value), record.labels)

    def observe_ms(self, name: str, *, value_ms: float, labels: Mapping[str, str] | None = None) -> None:
        record = MetricRecord(name=name, value=float(value_ms), labels=sanitize_metric_labels(labels))
        self._logger.info("metric_observe_ms name=%s value_ms=%.3f labels=%s", record.name, record.value, record.labels)


__all__ = [
    "LoggingMetricsPort",
    "MetricRecord",
    "MetricsPort",
    "NoopMetricsPort",
    "ObservabilityContext",
    "OperationTimer",
    "build_operation_labels",
    "sanitize_metric_labels",
]
