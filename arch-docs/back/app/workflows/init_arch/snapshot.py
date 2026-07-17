from __future__ import annotations

import datetime
import typing

import pydantic
import yaml

from app.workflows.init_arch.domain import WorkflowSessionRecord

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
