"""Transport-agnostic contracts for application-layer use-cases."""

from .dto import ActorRef, CallbackActionRequest, ChatRef, GroupDispatchRequest, MessageRef, PrivateFieldSubmitRequest
from .error_transport import log_structured_error, to_api_error_payload, to_telegram_message
from .observability import (
    LoggingMetricsPort,
    MetricRecord,
    MetricsPort,
    NoopMetricsPort,
    ObservabilityContext,
    OperationTimer,
    build_operation_labels,
    sanitize_metric_labels,
)
from .errors import ErrorCode, map_exception_to_error, normalize_error_code, resolve_http_status
from .ports import PendingPort, QueuePort, RolePipelinePort, RuntimeStatusPort, StoragePort
from .result import AppError, Result
from .runtime_ops import (
    RuntimeOperation,
    RuntimeOperationRequest,
    RuntimeOperationResult,
    RuntimeOrchestrationPort,
    RuntimeState,
    RuntimeTransition,
)

__all__ = [
    "ActorRef",
    "AppError",
    "CallbackActionRequest",
    "ChatRef",
    "ErrorCode",
    "GroupDispatchRequest",
    "LoggingMetricsPort",
    "MetricRecord",
    "MetricsPort",
    "log_structured_error",
    "NoopMetricsPort",
    "ObservabilityContext",
    "OperationTimer",
    "to_api_error_payload",
    "to_telegram_message",
    "MessageRef",
    "PendingPort",
    "PrivateFieldSubmitRequest",
    "QueuePort",
    "Result",
    "RuntimeOperation",
    "RuntimeOperationRequest",
    "RuntimeOperationResult",
    "RuntimeOrchestrationPort",
    "RuntimeState",
    "RuntimeTransition",
    "RolePipelinePort",
    "RuntimeStatusPort",
    "StoragePort",
    "build_operation_labels",
    "map_exception_to_error",
    "normalize_error_code",
    "resolve_http_status",
    "sanitize_metric_labels",
]
