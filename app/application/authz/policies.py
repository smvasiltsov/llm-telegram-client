from __future__ import annotations

from app.application.contracts import ErrorCode, Result

from .contracts import AuthzAction, AuthzActor, AuthzDecision, AuthzResourceContext, AuthzRole


class OwnerOnlyAuthzService:
    """Owner-only baseline policy; contract is extensible for role-based rules."""

    def __init__(self, *, owner_user_id: int) -> None:
        self._owner_user_id = int(owner_user_id)

    def authorize(
        self,
        *,
        action: str | AuthzAction,
        actor: AuthzActor,
        resource_ctx: AuthzResourceContext | None = None,
    ) -> Result[AuthzDecision]:
        _ = resource_ctx
        normalized_action = action.value if isinstance(action, AuthzAction) else str(action)
        if int(actor.user_id) == self._owner_user_id:
            return Result.ok(
                AuthzDecision(
                    allowed=True,
                    reason=None,
                    required_role=AuthzRole.OWNER.value,
                    policy=normalized_action,
                )
            )
        return Result.fail(
            ErrorCode.AUTH_UNAUTHORIZED,
            "Unauthorized",
            details={
                "required_role": AuthzRole.OWNER.value,
                "actor_user_id": int(actor.user_id),
                "cause": "owner_only",
                "action": normalized_action,
            },
            http_status=403,
            retryable=False,
        )

