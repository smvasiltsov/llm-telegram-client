from __future__ import annotations

from skills_sdk.contract import SkillContext, SkillResult, SkillSpec


class TemplateSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="template.skill",
            name="Template Skill",
            version="0.1.0",
            description="Template model-callable skill.",
            input_schema={"type": "object"},
        )

    def validate_config(self, config: dict) -> list[str]:
        _ = config
        return []

    def run(self, ctx: SkillContext, arguments: dict, config: dict) -> SkillResult:
        return SkillResult(ok=True, output={"arguments": arguments, "config": config, "role": ctx.role_name})


def create_skill() -> TemplateSkill:
    return TemplateSkill()
