import fastapi
import pydantic

from app.services.git_ssh import get_public_key

router = fastapi.APIRouter()


class GitSshPublicKeyResponse(pydantic.BaseModel, frozen=True):
    public_key: str


@router.get("/git-ssh/public-key/")
async def get_git_ssh_public_key() -> GitSshPublicKeyResponse:
    public_key = await get_public_key()
    return GitSshPublicKeyResponse(public_key=public_key)
