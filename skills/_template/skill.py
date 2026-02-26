from __future__ import annotations

from app.mcp.skills_contract import SkillContext, SkillResult, SkillSpec


class TemplateSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="template",
            name="Template Skill",
            version="0.1.0",
            description="Template skill that returns input payload for local testing.",
            permissions=(),
            timeout_sec=15,
        )

    def validate_config(self, config: dict) -> list[str]:
        _ = config
        return []

    def run(self, ctx: SkillContext, payload: dict) -> SkillResult:
        return SkillResult(
            status="ok",
            output={
                "echo_payload": payload,
                "role": ctx.role_name,
                "chain_id": ctx.chain_id,
            },
        )


def create_skill() -> TemplateSkill:
    return TemplateSkill()
