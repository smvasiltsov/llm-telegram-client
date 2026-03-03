from __future__ import annotations

from skills_sdk.contract import SkillContext, SkillResult, SkillSpec


class EchoSkill:
    def describe(self) -> SkillSpec:
        return SkillSpec(
            skill_id="echo.skill",
            name="Echo Skill",
            version="0.1.0",
            description="Simple example skill that returns its arguments.",
            input_schema={"type": "object"},
        )

    def validate_config(self, config: dict) -> list[str]:
        if not isinstance(config, dict):
            return ["config must be an object"]
        return []

    def run(self, ctx: SkillContext, arguments: dict, config: dict) -> SkillResult:
        return SkillResult(ok=True, output={"echo": arguments, "role_name": ctx.role_name})


def create_skill() -> EchoSkill:
    return EchoSkill()
