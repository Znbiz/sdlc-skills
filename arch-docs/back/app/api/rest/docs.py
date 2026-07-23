from __future__ import annotations

import pydantic


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
