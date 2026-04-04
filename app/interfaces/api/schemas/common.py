from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ApiSchema(BaseModel):
    """Base schema for API boundary DTOs (Pydantic v2)."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        from_attributes=True,
        str_strip_whitespace=False,
    )


class ApiListResponse(ApiSchema):
    items: list[Any]


class ApiMessageResponse(ApiSchema):
    message: str
