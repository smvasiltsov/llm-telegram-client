from __future__ import annotations

from mcp_skill_sdk.skills_contract import SkillContext, SkillResult, SkillSpec


class EchoSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="echo",
            name="Echo Skill",
            version="0.1.0",
            description="Echoes selected payload fields for integration smoke.",
            permissions=(),
            timeout_sec=10,
        )

    def validate_config(self, config: dict) -> list[str]:
        if not isinstance(config, dict):
            return ["config must be an object"]
        return []

    def run(self, ctx: SkillContext, payload: dict) -> SkillResult:
        return SkillResult(
            status="ok",
            output={
                "chain_id": ctx.chain_id,
                "role_name": ctx.role_name,
                "keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
            },
        )


def create_skill() -> EchoSkill:
    return EchoSkill()
