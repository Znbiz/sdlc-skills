from __future__ import annotations

from app.services.task_runner import LlmCliService


class LlmWorkerService(LlmCliService):
    pass


_llm_worker_service: LlmWorkerService | None = None


def get_llm_worker_service() -> LlmWorkerService:
    global _llm_worker_service  # noqa: PLW0603
    if _llm_worker_service is None:
        _llm_worker_service = LlmWorkerService()
    return _llm_worker_service
