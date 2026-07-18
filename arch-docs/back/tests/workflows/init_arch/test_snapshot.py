from __future__ import annotations

import datetime as dt
import pathlib

import structlog.testing
import yaml

from app.workflows.init_arch import snapshot as snapshot_module
from app.workflows.init_arch.domain import RepositoryExecution, StepId, WorkflowSessionRecord


def _make_state() -> dict:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.CLONE_REPOSITORIES,
        completed_steps=[StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE],
        repositories=[RepositoryExecution(repository_name="svc-a", created_at=dt.date(2024, 1, 1))],
    )
    return {
        "session_id": "wf-1",
        "session": session,
        "workspace_dir": "/workspace/repo",
        "arch_repo_dir": "/workspace/repo/arch-doc",
        "engine_name": "claude",
        "timeout_seconds": 600,
        "progress_file_path": "/workspace/repo/arch-doc/repo-initialization-progress.yaml",
        "raw_workspace_dir": "/workspace/repo/.temp",
        "last_llm_result": None,
        "last_guard_output": "",
        "step_error": None,
        "retry_count": 0,
    }


def test_build_snapshot_captures_fields_not_present_on_workflow_session_record():
    state = _make_state()

    snapshot = snapshot_module.build_snapshot(state)

    assert snapshot.workflow_id == "wf-1"
    assert snapshot.workspace_dir == "/workspace/repo"
    assert snapshot.arch_repo_dir == "/workspace/repo/arch-doc"
    assert snapshot.engine_name == "claude"
    assert snapshot.timeout_seconds == 600
    assert snapshot.session.current_step is StepId.CLONE_REPOSITORIES
    assert snapshot.schema_version == 1


def test_dump_snapshot_yaml_produces_plain_readable_yaml():
    snapshot = snapshot_module.build_snapshot(_make_state())

    yaml_text = snapshot_module.dump_snapshot_yaml(snapshot)
    parsed = yaml.safe_load(yaml_text)

    assert parsed["workflow_id"] == "wf-1"
    assert parsed["session"]["current_step"] == "clone_repositories"
    assert parsed["session"]["repositories"][0]["repository_name"] == "svc-a"
    assert parsed["session"]["repositories"][0]["created_at"] == "2024-01-01"


def test_dump_then_parse_snapshot_yaml_round_trips():
    original = snapshot_module.build_snapshot(_make_state())

    yaml_text = snapshot_module.dump_snapshot_yaml(original)
    restored = snapshot_module.parse_snapshot_yaml(yaml_text)

    assert restored == original


def test_write_snapshot_file_writes_yaml_to_progress_file_path(tmp_path):
    progress_file = tmp_path / "arch-doc" / "repo-initialization-progress.yaml"
    state = _make_state()
    state["progress_file_path"] = str(progress_file)

    snapshot_module.write_snapshot_file(state)

    assert progress_file.exists()
    restored = snapshot_module.parse_snapshot_yaml(progress_file.read_text(encoding="utf-8"))
    assert restored.workflow_id == "wf-1"


def test_write_snapshot_file_overwrites_previous_content(tmp_path):
    progress_file = tmp_path / "progress.yaml"
    state = _make_state()
    state["progress_file_path"] = str(progress_file)

    snapshot_module.write_snapshot_file(state)
    state["session"] = state["session"].model_copy(update={"current_step": StepId.REFRESH_MAIN_BRANCHES})
    snapshot_module.write_snapshot_file(state)

    restored = snapshot_module.parse_snapshot_yaml(progress_file.read_text(encoding="utf-8"))
    assert restored.session.current_step is StepId.REFRESH_MAIN_BRANCHES


def test_write_snapshot_file_noop_when_progress_file_path_missing():
    state = _make_state()
    state["progress_file_path"] = ""

    snapshot_module.write_snapshot_file(state)  # не должно бросать исключение


def test_write_snapshot_file_swallows_errors_and_logs_warning(tmp_path):
    unwritable_dir = tmp_path / "not-a-directory"
    unwritable_dir.write_text("i am a file, not a directory")
    state = _make_state()
    state["progress_file_path"] = str(unwritable_dir / "progress.yaml")

    with structlog.testing.capture_logs() as captured:
        snapshot_module.write_snapshot_file(state)  # не должно бросать исключение

    assert any(entry["event"] == "workflow.snapshot_persist_failed" for entry in captured)


def test_write_snapshot_file_cleans_up_tmp_file_when_replace_fails(tmp_path, monkeypatch):
    arch_repo_dir = tmp_path / "arch-doc"
    arch_repo_dir.mkdir()
    state = _make_state()
    state["progress_file_path"] = str(arch_repo_dir / "repo-initialization-progress.yaml")

    def _boom(self, target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(pathlib.Path, "replace", _boom)

    with structlog.testing.capture_logs() as captured:
        snapshot_module.write_snapshot_file(state)  # не должно бросать исключение

    assert any(entry["event"] == "workflow.snapshot_persist_failed" for entry in captured)
    leftover_tmp_files = list(arch_repo_dir.glob("*.tmp"))
    assert leftover_tmp_files == []
