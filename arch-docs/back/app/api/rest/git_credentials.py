import fastapi
import pydantic

from app.services.git_credentials import check_git_access, delete_git_token, list_configured_hosts, set_git_token

router = fastapi.APIRouter()


class GitCredentialsStatusResponse(pydantic.BaseModel, frozen=True):
    configured: bool
    configured_hosts: list[str]


class SetPersonalAccessTokenRequest(pydantic.BaseModel, frozen=True):
    host: str
    token: str
    username: str | None = None

    @pydantic.field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or "/" in stripped or "://" in stripped:
            msg = "host must be a bare hostname, e.g. 'github.com'"
            raise ValueError(msg)
        return stripped

    @pydantic.field_validator("token")
    @classmethod
    def validate_token(cls, value: str) -> str:
        if not value.strip():
            msg = "token must not be empty"
            raise ValueError(msg)
        return value


class CheckGitAccessRequest(pydantic.BaseModel, frozen=True):
    repository_url: str

    @pydantic.field_validator("repository_url")
    @classmethod
    def validate_repository_url(cls, value: str) -> str:
        if not value.strip():
            msg = "repository_url must not be empty"
            raise ValueError(msg)
        return value


class CheckGitAccessResponse(pydantic.BaseModel, frozen=True):
    repository_url: str
    accessible: bool
    access_status: str
    reason_code: str | None
    message: str


async def _status_response() -> GitCredentialsStatusResponse:
    hosts = await list_configured_hosts()
    return GitCredentialsStatusResponse(configured=bool(hosts), configured_hosts=hosts)


@router.get("/git-credentials/")
async def get_git_credentials_status() -> GitCredentialsStatusResponse:
    return await _status_response()


@router.put("/git-credentials/personal-access-token/")
async def set_personal_access_token(request: SetPersonalAccessTokenRequest) -> GitCredentialsStatusResponse:
    await set_git_token(host=request.host, token=request.token, username=request.username)
    return await _status_response()


@router.delete("/git-credentials/personal-access-token/")
async def delete_personal_access_token(host: str) -> GitCredentialsStatusResponse:
    await delete_git_token(host)
    return await _status_response()


@router.post("/git-credentials/check-access/")
async def check_git_credentials_access(request: CheckGitAccessRequest) -> CheckGitAccessResponse:
    result = await check_git_access(request.repository_url)
    return CheckGitAccessResponse(
        repository_url=request.repository_url,
        accessible=result["accessible"],
        access_status=result["access_status"],
        reason_code=result["reason_code"],
        message=result["message"],
    )
