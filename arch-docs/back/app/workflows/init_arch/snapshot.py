from __future__ import annotations

import datetime
import pathlib
import tempfile
import typing

import pydantic
import structlog
import yaml

from app.workflows.init_arch.domain import WorkflowSessionRecord

logger = structlog.get_logger()

_SNAPSHOT_SCHEMA_VERSION: typing.Final[int] = 1


class WorkflowSnapshot(pydantic.BaseModel):
    schema_version: int = _SNAPSHOT_SCHEMA_VERSION
    workflow_id: str
    workspace_dir: str
    arch_repo_dir: str
    engine_name: str
    timeout_seconds: int
    updated_at: datetime.datetime
    session: WorkflowSessionRecord


def build_snapshot(state: typing.Mapping[str, typing.Any]) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        workflow_id=state["session_id"],
        workspace_dir=state["workspace_dir"],
        arch_repo_dir=state["arch_repo_dir"],
        engine_name=state["engine_name"],
        timeout_seconds=state["timeout_seconds"],
        updated_at=datetime.datetime.now(datetime.timezone.utc),
        session=state["session"],
    )


def dump_snapshot_yaml(snapshot: WorkflowSnapshot) -> str:
    payload = snapshot.model_dump(mode="json")
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def parse_snapshot_yaml(yaml_text: str) -> WorkflowSnapshot:
    payload = yaml.safe_load(yaml_text)
    return WorkflowSnapshot.model_validate(payload)


def write_snapshot_file(state: typing.Mapping[str, typing.Any]) -> None:
    progress_file_path = state.get("progress_file_path", "")
    if not progress_file_path:
        return
    try:
        yaml_text = dump_snapshot_yaml(build_snapshot(state))
        target_path = pathlib.Path(progress_file_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=target_path.parent, delete=False, suffix=".tmp", encoding="utf-8"
        ) as tmp_file:
            tmp_file.write(yaml_text)
            tmp_path = pathlib.Path(tmp_file.name)
        tmp_path.replace(target_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "workflow.snapshot_persist_failed",
            workflow_id=state.get("session_id", ""),
            error=str(exc),
        )
