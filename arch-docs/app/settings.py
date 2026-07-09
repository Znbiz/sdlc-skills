from __future__ import annotations

import functools

import pydantic
from pydantic_settings import BaseSettings, SettingsConfigDict


class InitWorkflowSettings(pydantic.BaseModel):
    historical_window_months: int = 3


class WorkflowsSettings(pydantic.BaseModel):
    init: InitWorkflowSettings = pydantic.Field(default_factory=InitWorkflowSettings)


class GatewaySettings(BaseSettings):
    auth_secret: str
    workspace_dir: str = "/workspace"
    default_timeout_seconds: int = 300
    skill_root_dir: str = "/app/skills"
    agent_pool_size: int = 4
    database_url: str = "postgresql+asyncpg://arch_docs:arch_docs@localhost:5432/arch_docs"
    workflows: WorkflowsSettings = pydantic.Field(default_factory=WorkflowsSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
    )


@functools.lru_cache(maxsize=1)
def get_gateway_settings() -> GatewaySettings:
    return GatewaySettings()
