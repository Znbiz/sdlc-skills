from pydantic_settings import BaseSettings


class GatewaySettings(BaseSettings):
    auth_secret: str
    workspace_dir: str = "/workspace"
    default_timeout_seconds: int = 300
    skill_root_dir: str = "/app/skills"
    agent_pool_size: int = 4
    database_url: str = "postgresql+asyncpg://ai_gateway:ai_gateway@localhost:5432/ai_gateway"

    model_config = {"env_file": ".env"}
