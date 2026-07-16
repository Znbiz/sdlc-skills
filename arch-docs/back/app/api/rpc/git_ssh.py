import fastapi
import pydantic

from app.services.git_ssh import check_git_access

router = fastapi.APIRouter()


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


@router.post("/git-ssh/check-access/")
async def check_git_ssh_access(request: CheckGitAccessRequest) -> CheckGitAccessResponse:
    result = await check_git_access(request.repository_url)
    return CheckGitAccessResponse(
        repository_url=request.repository_url,
        accessible=result["accessible"],
        access_status=result["access_status"],
        message=result["message"],
    )
