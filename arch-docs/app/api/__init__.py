import fastapi

from app.api.openai import router as openai_router
from app.api.rest.cli_auth import router as rest_cli_auth_router
from app.api.rest.conversations import router as rest_conversations_router
from app.api.rest.git_credentials import router as rest_git_credentials_router
from app.api.rest.tasks import router as rest_tasks_router
from app.api.rpc.cli_auth import router as rpc_cli_auth_router
from app.api.rpc.execute import router as rpc_execute_router


def setup_routers(app: fastapi.FastAPI) -> None:
    app.include_router(openai_router, tags=["openai"])
    app.include_router(rpc_execute_router, prefix="/api/rpc", tags=["rpc"])
    app.include_router(rpc_cli_auth_router, prefix="/api/rpc", tags=["rpc"])
    app.include_router(rest_tasks_router, prefix="/api/rest", tags=["rest"])
    app.include_router(rest_cli_auth_router, prefix="/api/rest", tags=["rest"])
    app.include_router(rest_git_credentials_router, prefix="/api/rest", tags=["rest"])
    app.include_router(rest_conversations_router, prefix="/api/rest", tags=["rest"])
