from __future__ import annotations

import functools

import pydantic
from pydantic_settings import BaseSettings, SettingsConfigDict


class InitWorkflowSettings(pydantic.BaseModel):
    historical_window_months: int = 3
    max_step_timeout_seconds: int = 900
    raw_workspace_subdir: str = ".temp"
    arch_repo_dirname: str = "arch-doc"


class WorkflowsSettings(pydantic.BaseModel):
    init: InitWorkflowSettings = pydantic.Field(default_factory=InitWorkflowSettings)


class AuditSettings(pydantic.BaseModel):
    max_prompt_chars: int = 12_000
    max_output_chars: int = 16_000
    max_error_chars: int = 8_000


class GatewaySettings(BaseSettings):
    auth_secret: str
    workspace_dir: str = "/workspace"
    default_timeout_seconds: int = 300
    skill_root_dir: str = "/app/skills"
    agent_pool_size: int = 4
    database_url: str = "postgresql+asyncpg://arch_docs:arch_docs@localhost:5432/arch_docs"
    workflows: WorkflowsSettings = pydantic.Field(default_factory=WorkflowsSettings)
    audit: AuditSettings = pydantic.Field(default_factory=AuditSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
    )


@functools.lru_cache(maxsize=1)
def get_gateway_settings() -> GatewaySettings:
    return GatewaySettings()
