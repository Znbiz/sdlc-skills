import fastapi

from app.api.rest.cli_auth import router as rest_cli_auth_router
from app.api.rest.tasks import router as rest_tasks_router
from app.api.rest.workflows import router as rest_workflows_router
from app.api.rpc.arch_ops import router as rpc_arch_ops_router
from app.api.rpc.cli_auth import router as rpc_cli_auth_router
from app.api.rpc.execute import router as rpc_execute_router
from app.api.rpc.workflows import router as rpc_workflows_router


def setup_routers(app: fastapi.FastAPI) -> None:
    app.include_router(rpc_execute_router, prefix="/api/rpc", tags=["rpc"])
    app.include_router(rpc_cli_auth_router, prefix="/api/rpc", tags=["rpc"])
    app.include_router(rpc_workflows_router, prefix="/api/rpc", tags=["rpc"])
    app.include_router(rpc_arch_ops_router, prefix="/api/rpc", tags=["rpc"])
    app.include_router(rest_tasks_router, prefix="/api/rest", tags=["rest"])
    app.include_router(rest_cli_auth_router, prefix="/api/rest", tags=["rest"])
    app.include_router(rest_workflows_router, prefix="/api/rest", tags=["rest"])
