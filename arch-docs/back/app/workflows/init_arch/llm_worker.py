from __future__ import annotations

import typing

from app.services.task_runner import FAILURE_REASON_LIMIT_EXHAUSTED, LlmCliService, LlmTaskExecutionError
from app.workflows.init_arch.domain import EventType, LlmTaskRequest

_SUPPORTED_ENGINES: typing.Final[tuple[str, str]] = ("claude", "codex")


class LlmWorkerService(LlmCliService):
    async def run_task(self, request: LlmTaskRequest, *, engine_name: str, provider_connection_id: str | None = None):
        try:
            return await super().run_task(
                request, engine_name=engine_name, provider_connection_id=provider_connection_id
            )
        except LlmTaskExecutionError as exc:
            if exc.reason != FAILURE_REASON_LIMIT_EXHAUSTED:
                raise
            if provider_connection_id is not None:
                # An external LLM connection was chosen explicitly by the user - silently
                # falling back to the other built-in engine would ignore that choice (and burn
                # a different provider's quota) instead of surfacing the external provider's own
                # rate limit. See
                # arch-docs/docs/spec/2026-07-24-external-llm-provider.md, section 5.
                raise

        fallback_engine = _alternative_engine(engine_name)
        self._record_event(
            request,
            EventType.LLM_TASK_FAILOVER_TRIGGERED,
            from_engine=engine_name,
            to_engine=fallback_engine,
            reason=FAILURE_REASON_LIMIT_EXHAUSTED,
        )

        try:
            return await super().run_task(request, engine_name=fallback_engine)
        except LlmTaskExecutionError as exc:
            if exc.reason != FAILURE_REASON_LIMIT_EXHAUSTED:
                raise

        message = _build_limit_exhausted_message(primary_engine=engine_name, fallback_engine=fallback_engine)
        self._record_event(
            request,
            EventType.LLM_TASK_FAILOVER_EXHAUSTED,
            primary_engine=engine_name,
            fallback_engine=fallback_engine,
            reason=FAILURE_REASON_LIMIT_EXHAUSTED,
        )
        raise RuntimeError(message)


_llm_worker_service: LlmWorkerService | None = None


def get_llm_worker_service() -> LlmWorkerService:
    global _llm_worker_service  # noqa: PLW0603
    if _llm_worker_service is None:
        _llm_worker_service = LlmWorkerService()
    return _llm_worker_service


def _alternative_engine(engine_name: str) -> str:
    for candidate in _SUPPORTED_ENGINES:
        if candidate != engine_name:
            return candidate
    raise ValueError(f"Unsupported engine for failover: {engine_name}")


def _build_limit_exhausted_message(*, primary_engine: str, fallback_engine: str) -> str:
    return (
        "LLM limits exhausted for all supported engines "
        f"({primary_engine}, {fallback_engine}); workflow cannot continue until limits refresh"
    )
