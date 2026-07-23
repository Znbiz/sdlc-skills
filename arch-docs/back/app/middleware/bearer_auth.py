import typing

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_OPEN_PATHS: frozenset[str] = frozenset({"/health", "/api-docs", "/openapi.json", "/api-redoc"})


class BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: typing.Any, auth_secret: str) -> None:
        super().__init__(app)
        self._auth_secret = auth_secret

    async def dispatch(self, request: Request, call_next: typing.Callable) -> Response:
        if request.url.path in _OPEN_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[len("Bearer ") :]
        if token != self._auth_secret:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid token"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        return await call_next(request)
