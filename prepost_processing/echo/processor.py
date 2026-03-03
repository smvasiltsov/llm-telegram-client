from __future__ import annotations

from prepost_processing_sdk.contract import (
    PrePostProcessingContext,
    PrePostProcessingResult,
    PrePostProcessingSpec,
)


class EchoPrePostProcessing:
    def describe(self) -> PrePostProcessingSpec:
        return PrePostProcessingSpec(
            prepost_processing_id="echo",
            name="Echo Pre/Post Processing",
            version="0.1.0",
            description="Echoes selected payload fields for integration smoke.",
            permissions=(),
            timeout_sec=10,
        )

    def validate_config(self, config: dict) -> list[str]:
        if not isinstance(config, dict):
            return ["config must be an object"]
        return []

    def run(self, ctx: PrePostProcessingContext, payload: dict) -> PrePostProcessingResult:
        return PrePostProcessingResult(
            status="ok",
            output={
                "chain_id": ctx.chain_id,
                "role_name": ctx.role_name,
                "keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
            },
        )


def create_processor() -> EchoPrePostProcessing:
    return EchoPrePostProcessing()
