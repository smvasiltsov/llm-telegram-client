from __future__ import annotations


class ToolError(Exception):
    """Base exception for tool execution errors."""


class ToolValidationError(ToolError):
    """Raised when tool input is invalid."""


class ToolPermissionError(ToolError):
    """Raised when caller is not allowed to run a tool."""


class ToolAuthRequiredError(ToolPermissionError):
    """Raised when tool execution requires additional password confirmation."""


class ToolTimeoutError(ToolError):
    """Raised when tool execution exceeds configured timeout."""
