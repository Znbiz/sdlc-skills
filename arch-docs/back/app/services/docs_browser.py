from __future__ import annotations

import datetime
import enum
import pathlib
import typing


class MediaKind(enum.StrEnum):
    MARKDOWN = enum.auto()
    YAML = enum.auto()
    JSON = enum.auto()
    TEXT = enum.auto()
    UNSUPPORTED = enum.auto()


class DocsPathForbiddenError(ValueError):
    pass


class DocsFileNotFoundError(LookupError):
    pass


_MEDIA_KIND_BY_SUFFIX: typing.Final[dict[str, MediaKind]] = {
    ".md": MediaKind.MARKDOWN,
    ".markdown": MediaKind.MARKDOWN,
    ".yaml": MediaKind.YAML,
    ".yml": MediaKind.YAML,
    ".json": MediaKind.JSON,
    ".txt": MediaKind.TEXT,
    ".rst": MediaKind.TEXT,
}


def detect_media_kind(path: pathlib.Path) -> MediaKind:
    return _MEDIA_KIND_BY_SUFFIX.get(path.suffix.lower(), MediaKind.UNSUPPORTED)


def resolve_within_root(arch_repo_root: str, relative_path: str) -> pathlib.Path:
    root = pathlib.Path(arch_repo_root).expanduser().resolve()
    candidate = (root / relative_path).resolve()

    if candidate != root and root not in candidate.parents:
        raise DocsPathForbiddenError(f"Path {relative_path!r} escapes arch_repo_root")
    if not candidate.exists():
        raise DocsFileNotFoundError(f"Path {relative_path!r} does not exist")
    return candidate


def _node_metadata(path: pathlib.Path, *, root: pathlib.Path) -> dict[str, typing.Any]:
    stat = path.stat()
    return {
        "path": str(path.relative_to(root)) if path != root else "",
        "name": path.name if path != root else "",
        "size": stat.st_size,
        "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat(),
    }


def _build_node(path: pathlib.Path, *, root: pathlib.Path) -> dict[str, typing.Any]:
    metadata = _node_metadata(path, root=root)
    if path.is_dir():
        children = sorted(
            (child for child in path.iterdir() if not child.is_symlink()),
            key=lambda child: (child.is_file(), child.name),
        )
        return {
            **metadata,
            "node_type": "directory",
            "children": [_build_node(child, root=root) for child in children],
            "media_kind": None,
        }
    return {
        **metadata,
        "node_type": "file",
        "children": None,
        "media_kind": detect_media_kind(path).value,
    }


def build_docs_tree(arch_repo_root: str) -> dict[str, typing.Any]:
    root = pathlib.Path(arch_repo_root).expanduser().resolve()
    return _build_node(root, root=root)


def read_docs_file(arch_repo_root: str, relative_path: str) -> dict[str, typing.Any]:
    resolved = resolve_within_root(arch_repo_root, relative_path)
    if resolved.is_dir():
        raise DocsFileNotFoundError(f"Path {relative_path!r} is a directory, not a file")

    media_kind = detect_media_kind(resolved)
    stat = resolved.stat()
    base = {
        "path": relative_path,
        "name": resolved.name,
        "media_kind": media_kind.value,
        "size": stat.st_size,
        "modified_at": datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat(),
    }

    if media_kind == MediaKind.UNSUPPORTED:
        return {**base, "content": None, "encoding": None}

    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {**base, "media_kind": MediaKind.UNSUPPORTED.value, "content": None, "encoding": None}

    return {**base, "content": content, "encoding": "utf-8"}
