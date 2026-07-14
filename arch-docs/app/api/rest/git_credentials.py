import fastapi
import pydantic

from app.services.git_credentials import list_configured_hosts

router = fastapi.APIRouter()


class GitCredentialsStatusResponse(pydantic.BaseModel, frozen=True):
    configured_hosts: list[str]


@router.get("/git-credentials/")
async def get_git_credentials_status() -> GitCredentialsStatusResponse:
    hosts = await list_configured_hosts()
    return GitCredentialsStatusResponse(configured_hosts=hosts)
