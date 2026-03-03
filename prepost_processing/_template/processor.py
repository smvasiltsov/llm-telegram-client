from __future__ import annotations

from prepost_processing_sdk.contract import (
    PrePostProcessingContext,
    PrePostProcessingResult,
    PrePostProcessingSpec,
)


class TemplatePrePostProcessing:
    def describe(self) -> PrePostProcessingSpec:
        return PrePostProcessingSpec(
            prepost_processing_id="template",
            name="Template Pre/Post Processing",
            version="0.1.0",
            description="Template pre/post processing that returns input payload for local testing.",
            permissions=(),
            timeout_sec=15,
        )

    def validate_config(self, config: dict) -> list[str]:
        _ = config
        return []

    def run(self, ctx: PrePostProcessingContext, payload: dict) -> PrePostProcessingResult:
        return PrePostProcessingResult(
            status="ok",
            output={
                "echo_payload": payload,
                "role": ctx.role_name,
                "chain_id": ctx.chain_id,
            },
        )


def create_processor() -> TemplatePrePostProcessing:
    return TemplatePrePostProcessing()
