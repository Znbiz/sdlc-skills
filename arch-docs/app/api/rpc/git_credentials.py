import fastapi
import pydantic

from app.services.git_credentials import check_git_access, list_configured_hosts, set_git_token

router = fastapi.APIRouter()


class SetGitTokenRequest(pydantic.BaseModel, frozen=True):
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


class SetGitTokenResponse(pydantic.BaseModel, frozen=True):
    configured_hosts: list[str]


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
    message: str


@router.post("/git-credentials/set/", status_code=fastapi.status.HTTP_202_ACCEPTED)
async def set_git_credentials(request: SetGitTokenRequest) -> SetGitTokenResponse:
    await set_git_token(host=request.host, token=request.token, username=request.username)
    hosts = await list_configured_hosts()
    return SetGitTokenResponse(configured_hosts=hosts)


@router.post("/git-credentials/check-access/")
async def check_git_credentials_access(request: CheckGitAccessRequest) -> CheckGitAccessResponse:
    result = await check_git_access(request.repository_url)
    return CheckGitAccessResponse(
        repository_url=request.repository_url,
        accessible=result["accessible"],
        access_status=result["access_status"],
        message=result["message"],
    )
