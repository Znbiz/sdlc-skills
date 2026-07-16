from __future__ import annotations

import typing

import fastapi
import pydantic
from fastapi import status

from app.services.docs_browser import (
    DocsFileNotFoundError,
    DocsPathForbiddenError,
    build_docs_tree,
    read_docs_file,
)
from app.services.init_arch_workflow import (
    ArchRepoNotAvailableError,
    WorkflowNotFoundError,
    get_response_arch_repo_dir_async,
)
from app.services.status_taxonomy import ReasonCode

router = fastapi.APIRouter()


class DocsTreeNode(pydantic.BaseModel, frozen=True):
    path: str
    name: str
    node_type: str
    children: list["DocsTreeNode"] | None
    size: int
    modified_at: str
    media_kind: str | None


class DocsFileResponse(pydantic.BaseModel, frozen=True):
    path: str
    name: str
    media_kind: str
    content: str | None
    encoding: str | None
    size: int
    modified_at: str


async def _resolve_arch_repo_dir(response_id: str) -> str:
    try:
        return await get_response_arch_repo_dir_async(response_id)
    except WorkflowNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ArchRepoNotAvailableError as exc:
        raise fastapi.HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason_code": ReasonCode.ARCH_REPO_MISSING_FOR_RESPONSE.value, "message": str(exc)},
        ) from exc


@router.get("/responses/{response_id}/docs/tree/")
async def get_docs_tree(response_id: str) -> DocsTreeNode:
    arch_repo_dir = await _resolve_arch_repo_dir(response_id)
    tree = build_docs_tree(arch_repo_dir)
    return DocsTreeNode.model_validate(tree)


@router.get("/responses/{response_id}/docs/file/")
async def get_docs_file(response_id: str, path: str) -> DocsFileResponse:
    arch_repo_dir = await _resolve_arch_repo_dir(response_id)
    try:
        file_payload: dict[str, typing.Any] = read_docs_file(arch_repo_dir, path)
    except DocsPathForbiddenError as exc:
        raise fastapi.HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"reason_code": ReasonCode.PATH_FORBIDDEN.value, "message": str(exc)},
        ) from exc
    except DocsFileNotFoundError as exc:
        raise fastapi.HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DocsFileResponse.model_validate(file_payload)
