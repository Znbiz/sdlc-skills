from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "init-repo-arch-skill"
SCRIPT_PATH = SKILL_ROOT / "scripts" / "analysis_guard.py"
FIXTURES_ROOT = SKILL_ROOT / "tests" / "fixtures"

sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from analysis_guard.commands import _build_temporal_delta  # noqa: E402
from analysis_guard.knowledge import run_knowledge_lint  # noqa: E402


def _create_git_repo_with_commits(repo_path: Path, commits: list[tuple[str, str]]) -> list[str]:
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Codex Test"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "codex@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    commit_ids: list[str] = []
    tracked_file = repo_path / "payload.txt"
    for index, (commit_date, content) in enumerate(commits, start=1):
        tracked_file.write_text(f"{content}\n", encoding="utf-8")
        subprocess.run(["git", "add", "payload.txt"], cwd=repo_path, check=True, capture_output=True)
        env = dict(os.environ)
        env["GIT_AUTHOR_DATE"] = f"{commit_date}T12:00:00+00:00"
        env["GIT_COMMITTER_DATE"] = f"{commit_date}T12:00:00+00:00"
        subprocess.run(
            ["git", "commit", "-m", f"commit-{index}"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            env=env,
        )
        rev_parse = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        commit_ids.append(rev_parse.stdout.strip())
    return commit_ids


class AnalysisGuardKnowledgeTests(unittest.TestCase):
    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def _create_git_repo_with_commits(self, repo_path: Path, commits: list[tuple[str, str]]) -> list[str]:
        return _create_git_repo_with_commits(repo_path, commits)

    def test_timeline_plan_resolve_checkout_and_advance_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            old_repo_path = temp_path / "old-repo"
            new_repo_path = temp_path / "new-repo"
            old_commits = self._create_git_repo_with_commits(
                old_repo_path,
                [
                    ("2021-01-15", "old-1"),
                    ("2021-05-01", "old-2"),
                ],
            )
            new_commits = self._create_git_repo_with_commits(
                new_repo_path,
                [
                    ("2021-02-10", "new-1"),
                    ("2021-06-20", "new-2"),
                ],
            )

            progress_path = temp_path / "repo-initialization-progress.json"
            init_result = self._run_cli(
                "init",
                "--output",
                str(progress_path),
                "--product",
                "Historical Product",
                "--scope",
                "full",
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            register_old = self._run_cli(
                "repo",
                "--progress",
                str(progress_path),
                "--name",
                "old-repo",
                "--register",
                "--role",
                "backend-api",
                "--created-at",
                "2021-01-15",
                "--repository-url",
                "git@example.com/old-repo.git",
                "--local-path",
                str(old_repo_path),
                "--main-branch",
                "main",
            )
            self.assertEqual(register_old.returncode, 0, register_old.stderr)

            register_new = self._run_cli(
                "repo",
                "--progress",
                str(progress_path),
                "--name",
                "new-repo",
                "--register",
                "--role",
                "backend-api",
                "--created-at",
                "2021-02-10",
                "--repository-url",
                "git@example.com/new-repo.git",
                "--local-path",
                str(new_repo_path),
                "--main-branch",
                "main",
            )
            self.assertEqual(register_new.returncode, 0, register_new.stderr)

            plan_result = self._run_cli(
                "timeline",
                "--progress",
                str(progress_path),
                "--plan",
            )
            self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
            self.assertIn("anchor=old-repo", plan_result.stdout)
            self.assertIn("snapshot_at=2021-04-15", plan_result.stdout)

            resolve_result = self._run_cli(
                "timeline",
                "--progress",
                str(progress_path),
                "--resolve-local",
                "--checkout",
            )
            self.assertEqual(resolve_result.returncode, 0, resolve_result.stderr)
            self.assertIn("Resolved historical commits for snapshot 2021-04-15: resolved=2, missing=0", resolve_result.stdout)

            progress_data = json.loads(progress_path.read_text(encoding="utf-8"))
            ordered_names = progress_data["analysis_progress"]["repository_execution"]["ordered_repository_names"]
            self.assertEqual(ordered_names, ["old-repo", "new-repo"])
            historical = progress_data["analysis_progress"]["historical_analysis"]
            self.assertEqual(historical["anchor_repository"], "old-repo")
            self.assertEqual(historical["current_snapshot_at"], "2021-04-15")

            repositories = {
                repo["name"]: repo
                for repo in progress_data["analysis_progress"]["repositories"]
            }
            self.assertEqual(repositories["old-repo"]["analysis_target_commit"], old_commits[0])
            self.assertEqual(repositories["new-repo"]["analysis_target_commit"], new_commits[0])
            self.assertEqual(repositories["old-repo"]["analysis_target_commit_status"], "checked_out")
            self.assertEqual(repositories["new-repo"]["analysis_target_commit_status"], "checked_out")
            # First window: only one commit precedes the snapshot date for each repo, so the
            # resolved baseline (first commit) equals the target commit itself -> no_changes.
            self.assertEqual(repositories["old-repo"]["commit_range_status"], "no_changes")
            self.assertEqual(repositories["old-repo"]["window_start_commit"], old_commits[0])
            self.assertEqual(repositories["old-repo"]["window_end_commit"], old_commits[0])
            self.assertEqual(repositories["old-repo"]["commit_range"], "")
            self.assertEqual(repositories["new-repo"]["commit_range_status"], "no_changes")

            old_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=old_repo_path,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(old_head.stdout.strip(), old_commits[0])

            advance_result = self._run_cli(
                "timeline",
                "--progress",
                str(progress_path),
                "--advance-window",
            )
            self.assertEqual(advance_result.returncode, 0, advance_result.stderr)
            self.assertIn("previous=2021-04-15 current=2021-07-15", advance_result.stdout)

            progress_after_advance = json.loads(progress_path.read_text(encoding="utf-8"))
            historical_after_advance = progress_after_advance["analysis_progress"]["historical_analysis"]
            self.assertEqual(historical_after_advance["current_snapshot_at"], "2021-07-15")
            self.assertEqual(historical_after_advance["previous_snapshot_at"], "2021-04-15")
            self.assertEqual(historical_after_advance["completed_snapshot_dates"], ["2021-04-15"])

            repositories_after_advance = {
                repo["name"]: repo
                for repo in progress_after_advance["analysis_progress"]["repositories"]
            }
            # advance-window must carry the just-closed window's resolved commit forward as the
            # next window's baseline, and reset the rest of the temporal-delta fields.
            self.assertEqual(
                repositories_after_advance["old-repo"]["previous_analysis_target_commit"], old_commits[0]
            )
            self.assertEqual(
                repositories_after_advance["new-repo"]["previous_analysis_target_commit"], new_commits[0]
            )
            self.assertEqual(repositories_after_advance["old-repo"]["commit_range_status"], "not_started")
            self.assertEqual(repositories_after_advance["old-repo"]["analysis_target_commit"], "")

            second_resolve_result = self._run_cli(
                "timeline",
                "--progress",
                str(progress_path),
                "--resolve-local",
            )
            self.assertEqual(second_resolve_result.returncode, 0, second_resolve_result.stderr)

            progress_after_second_resolve = json.loads(progress_path.read_text(encoding="utf-8"))
            repositories_after_second_resolve = {
                repo["name"]: repo
                for repo in progress_after_second_resolve["analysis_progress"]["repositories"]
            }
            # Second window: each repo gained one new commit since its window-1 baseline, so the
            # range is a real diff_collected delta, not a degenerate no_changes/baseline_missing case.
            self.assertEqual(repositories_after_second_resolve["old-repo"]["analysis_target_commit"], old_commits[1])
            self.assertEqual(repositories_after_second_resolve["old-repo"]["commit_range_status"], "diff_collected")
            self.assertEqual(
                repositories_after_second_resolve["old-repo"]["window_start_commit"], old_commits[0]
            )
            self.assertEqual(repositories_after_second_resolve["old-repo"]["window_end_commit"], old_commits[1])
            self.assertEqual(
                repositories_after_second_resolve["old-repo"]["commit_range"],
                f"{old_commits[0]}..{old_commits[1]}",
            )
            self.assertIn("payload.txt", repositories_after_second_resolve["old-repo"]["changed_paths"])
            self.assertTrue(repositories_after_second_resolve["old-repo"]["diff_stat_summary"])
            self.assertTrue(repositories_after_second_resolve["old-repo"]["commit_log_summary"])
            self.assertEqual(repositories_after_second_resolve["new-repo"]["commit_range_status"], "diff_collected")

    def test_validate_rejects_historical_order_and_snapshot_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            progress_path = temp_path / "repo-initialization-progress.json"

            init_result = self._run_cli(
                "init",
                "--output",
                str(progress_path),
                "--product",
                "Historical Product",
                "--scope",
                "full",
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            progress_data = json.loads(progress_path.read_text(encoding="utf-8"))
            for step in progress_data["analysis_progress"]["workflow"]["steps"]:
                if step["id"] in {
                    "define_scope",
                    "request_repository_list",
                    "prepare_temp_workspace",
                    "clone_repositories",
                    "refresh_main_branches",
                    "plan_repository_order",
                    "assess_scope_and_domains",
                }:
                    step["status"] = "completed"
                elif step["id"] == "analyze_repositories":
                    step["status"] = "in_progress"
            progress_data["analysis_progress"]["workflow"]["current_step_id"] = "analyze_repositories"
            progress_data["analysis_progress"]["current_position"]["current_step"] = "analyze_repositories"
            progress_data["analysis_progress"]["repository_execution"] = {
                "ordered_repository_names": ["new-repo", "old-repo"],
                "current_repository": "",
                "completed_repository_names": [],
            }
            progress_data["analysis_progress"]["historical_analysis"]["anchor_repository"] = "old-repo"
            progress_data["analysis_progress"]["historical_analysis"]["anchor_created_at"] = "2021-01-15"
            progress_data["analysis_progress"]["historical_analysis"]["current_snapshot_at"] = "2021-04-15"
            progress_data["analysis_progress"]["repositories"] = [
                {
                    "name": "old-repo",
                    "created_at": "2021-01-15",
                    "analysis_target_date": "2021-04-15",
                    "analysis_target_commit_status": "resolved",
                    "analysis_status": "not_started",
                    "in_scope": True,
                },
                {
                    "name": "new-repo",
                    "created_at": "2021-02-10",
                    "analysis_target_date": "2021-05-01",
                    "analysis_target_commit_status": "resolved",
                    "analysis_status": "not_started",
                    "in_scope": True,
                },
            ]
            progress_path.write_text(
                json.dumps(progress_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            validate_result = self._run_cli(
                "validate",
                "--progress",
                str(progress_path),
            )
            self.assertEqual(validate_result.returncode, 1)
            self.assertIn(
                "ordered_repository_names must be sorted by repository created_at for historical analysis mode.",
                validate_result.stdout,
            )
            self.assertIn(
                "historical snapshot date must be propagated to all in-scope repositories: new-repo",
                validate_result.stdout,
            )

    def test_validate_rejects_missing_temporal_delta_and_invalid_commit_range_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            progress_path = temp_path / "repo-initialization-progress.json"

            init_result = self._run_cli(
                "init",
                "--output",
                str(progress_path),
                "--product",
                "Historical Product",
                "--scope",
                "full",
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            progress_data = json.loads(progress_path.read_text(encoding="utf-8"))
            for step in progress_data["analysis_progress"]["workflow"]["steps"]:
                if step["id"] == "analyze_repositories" or step["id"] in {
                    "define_scope",
                    "request_repository_list",
                    "prepare_temp_workspace",
                    "clone_repositories",
                    "refresh_main_branches",
                    "plan_repository_order",
                    "assess_scope_and_domains",
                }:
                    step["status"] = "completed"
                elif step["id"] == "interview_user":
                    step["status"] = "in_progress"
            progress_data["analysis_progress"]["workflow"]["current_step_id"] = "interview_user"
            progress_data["analysis_progress"]["current_position"]["current_step"] = "interview_user"
            progress_data["analysis_progress"]["repository_execution"] = {
                "ordered_repository_names": ["old-repo"],
                "current_repository": "",
                "completed_repository_names": ["old-repo"],
            }
            progress_data["analysis_progress"]["historical_analysis"]["anchor_repository"] = "old-repo"
            progress_data["analysis_progress"]["historical_analysis"]["anchor_created_at"] = "2021-01-15"
            progress_data["analysis_progress"]["historical_analysis"]["current_snapshot_at"] = "2021-04-15"
            progress_data["analysis_progress"]["repositories"] = [
                {
                    "name": "old-repo",
                    "created_at": "2021-01-15",
                    "analysis_target_date": "2021-04-15",
                    "analysis_target_commit": "abc123",
                    "analysis_target_commit_status": "resolved",
                    "commit_range_status": "range_resolved",
                    "analysis_status": "completed",
                    "in_scope": True,
                },
            ]
            progress_path.write_text(
                json.dumps(progress_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            validate_result = self._run_cli(
                "validate",
                "--progress",
                str(progress_path),
            )
            self.assertEqual(validate_result.returncode, 1)
            self.assertIn(
                "analyze_repositories cannot be completed until temporal delta (commit_range/diff) "
                "is built for every repository: old-repo",
                validate_result.stdout,
            )

            progress_data["analysis_progress"]["repositories"][0]["commit_range_status"] = "not-a-real-status"
            progress_path.write_text(
                json.dumps(progress_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            invalid_status_result = self._run_cli(
                "validate",
                "--progress",
                str(progress_path),
            )
            self.assertEqual(invalid_status_result.returncode, 1)
            self.assertIn(
                "Repository old-repo has invalid commit_range_status: not-a-real-status",
                invalid_status_result.stdout,
            )

    def test_bootstrap_command_creates_wiki_scaffold_and_updates_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            arch_repo_path = temp_path / "arch-repo"
            progress_path = temp_path / "repo-initialization-progress.json"

            init_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "init",
                    "--output",
                    str(progress_path),
                    "--product",
                    "AI CLI Gateway Service",
                    "--scope",
                    "full",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            bootstrap_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "bootstrap",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap_result.returncode, 0, bootstrap_result.stderr)
            self.assertIn("Bootstrapped wiki layout:", bootstrap_result.stdout)

            wiki_index_path = arch_repo_path / "wiki" / "index.md"
            wiki_log_path = arch_repo_path / "wiki" / "log.md"
            compile_report_path = arch_repo_path / "wiki" / "maps" / "compile-report.md"
            self.assertTrue(wiki_index_path.exists())
            self.assertTrue(wiki_log_path.exists())
            self.assertTrue(compile_report_path.exists())

            wiki_index = wiki_index_path.read_text(encoding="utf-8")
            compile_report = compile_report_path.read_text(encoding="utf-8")
            self.assertIn("# Индекс знаний по системе AI CLI Gateway Service", wiki_index)
            self.assertIn("## Quality Gates", compile_report)

            progress_data = json.loads(progress_path.read_text(encoding="utf-8"))
            artifacts = progress_data["analysis_progress"]["artifacts"]
            self.assertEqual(artifacts["index"]["status"], "in_progress")
            self.assertEqual(artifacts["knowledge_log"]["status"], "completed")
            self.assertEqual(artifacts["compile_report"]["status"], "in_progress")

    def test_status_advance_and_validate_cover_knowledge_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            arch_repo_path = temp_path / "arch-repo"
            shutil.copytree(FIXTURES_ROOT / "valid_arch_repo", arch_repo_path)

            progress_path = temp_path / "repo-initialization-progress.json"
            init_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "init",
                    "--output",
                    str(progress_path),
                    "--product",
                    "AI CLI Gateway Service",
                    "--scope",
                    "full",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            progress_data = json.loads(progress_path.read_text(encoding="utf-8"))
            completed_step_ids = {
                "define_scope",
                "request_repository_list",
                "prepare_temp_workspace",
                "clone_repositories",
                "refresh_main_branches",
                "plan_repository_order",
                "assess_scope_and_domains",
                "analyze_repositories",
                "interview_user",
                "refine_features",
            }
            for step in progress_data["analysis_progress"]["workflow"]["steps"]:
                if step["id"] in completed_step_ids:
                    step["status"] = "completed"
                elif step["id"] == "build_navigation_index":
                    step["status"] = "in_progress"
            progress_data["analysis_progress"]["workflow"]["current_step_id"] = "build_navigation_index"
            progress_data["analysis_progress"]["current_position"]["current_step"] = "build_navigation_index"
            progress_data["analysis_progress"]["repositories"] = [
                {
                    "name": "gateway-service",
                    "created_at": "2026-01-01",
                    "analysis_target_date": "2026-04-01",
                    "analysis_target_commit": "abc123",
                    "analysis_target_commit_status": "checked_out",
                    "commit_range_status": "no_changes",
                    "analysis_status": "completed",
                    "in_scope": True,
                    "domain_map": {
                        "assessed_at": "2026-01-01T00:00:00+00:00",
                        "strategy": "per_module",
                        "volume_class": "small",
                        "total_files_estimate": 10,
                        "domains": [],
                        "domain_execution": {
                            "ordered_domain_ids": [],
                            "current_domain_id": "",
                            "completed_domain_ids": [],
                        },
                    },
                    "analysis_checklist": {
                        item_id: {"status": "completed", "notes": "", "title": title}
                        for item_id, title in (
                            ("scope_and_domain_assessment", ""),
                            ("repository_classification", ""),
                            ("repository_structure_mapping", ""),
                            ("entrypoints_and_interfaces", ""),
                            ("business_flow_orchestration", ""),
                            ("configs_and_runtime", ""),
                            ("tech_stack_collection", ""),
                            ("contracts_and_schemas", ""),
                            ("data_and_storage", ""),
                            ("domain_entities", ""),
                            ("integrations_and_dependencies", ""),
                            ("tests_and_behavior_evidence", ""),
                            ("glossary_updates", ""),
                            ("open_questions_review_and_updates", ""),
                            ("feature_discovery_and_updates", ""),
                            ("features_index_updates", ""),
                            ("roles_and_permissions_updates", ""),
                            ("security_and_auth_updates", ""),
                            ("deployment_and_operability", ""),
                            ("risks_and_tech_debt_updates", ""),
                            ("architecture_artifact_updates", ""),
                            ("repository_consistency_review", ""),
                        )
                    },
                },
            ]
            progress_data["analysis_progress"]["repository_execution"] = {
                "ordered_repository_names": ["gateway-service"],
                "current_repository": "",
                "completed_repository_names": ["gateway-service"],
            }
            progress_data["analysis_progress"]["historical_analysis"]["anchor_repository"] = "gateway-service"
            progress_data["analysis_progress"]["historical_analysis"]["anchor_created_at"] = "2026-01-01"
            progress_data["analysis_progress"]["historical_analysis"]["current_snapshot_at"] = "2026-04-01"
            progress_data["analysis_progress"]["validation"]["intermediate_status"] = "completed"
            progress_path.write_text(
                json.dumps(progress_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            bootstrap_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "bootstrap",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                    "--force",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(bootstrap_result.returncode, 0, bootstrap_result.stderr)

            status_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "status",
                    "--progress",
                    str(progress_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            self.assertIn("current_step: build_navigation_index", status_result.stdout)
            self.assertIn("knowledge_lint_status: not_started", status_result.stdout)
            self.assertIn("temporal_delta: range_status=no_changes", status_result.stdout)

            compile_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "compile",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

            validate_before_advance = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "validate",
                    "--progress",
                    str(progress_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(validate_before_advance.returncode, 0, validate_before_advance.stdout)

            advance_index = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "advance",
                    "--progress",
                    str(progress_path),
                    "--step",
                    "build_navigation_index",
                    "--note",
                    "navigation собран",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(advance_index.returncode, 0, advance_index.stderr)
            self.assertIn("Current step: run_knowledge_lint", advance_index.stdout)

            lint_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "lint",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(lint_result.returncode, 0, lint_result.stdout)
            self.assertIn("Knowledge issues:", lint_result.stdout)
            self.assertNotIn("ERROR:", lint_result.stdout)

            advance_lint = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "advance",
                    "--progress",
                    str(progress_path),
                    "--step",
                    "run_knowledge_lint",
                    "--note",
                    "knowledge lint пройден",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(advance_lint.returncode, 0, advance_lint.stderr)
            self.assertIn("Current step: validate_final", advance_lint.stdout)

            validate_after_advance = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "validate",
                    "--progress",
                    str(progress_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(validate_after_advance.returncode, 0, validate_after_advance.stdout)

    def test_analysis_guard_smoke_flow_generates_wiki_index_and_passes_lint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            arch_repo_path = temp_path / "arch-repo"
            shutil.copytree(FIXTURES_ROOT / "valid_arch_repo", arch_repo_path)

            progress_path = temp_path / "repo-initialization-progress.json"
            init_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "init",
                    "--output",
                    str(progress_path),
                    "--product",
                    "AI CLI Gateway Service",
                    "--scope",
                    "full",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            progress_data = json.loads(progress_path.read_text(encoding="utf-8"))
            completed_step_ids = {
                "define_scope",
                "request_repository_list",
                "prepare_temp_workspace",
                "clone_repositories",
                "refresh_main_branches",
            }
            for step in progress_data["analysis_progress"]["workflow"]["steps"]:
                if step["id"] in completed_step_ids:
                    step["status"] = "completed"
            progress_data["analysis_progress"]["repositories"] = [
                {
                    "name": "gateway-service",
                    "analysis_status": "completed",
                },
                {
                    "name": "gateway-web",
                    "analysis_status": "completed",
                },
            ]
            progress_path.write_text(
                json.dumps(progress_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            index_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "index",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(index_result.returncode, 0, index_result.stderr)

            generated_index = (arch_repo_path / "wiki" / "index.md").read_text(encoding="utf-8")
            generated_log = (arch_repo_path / "wiki" / "log.md").read_text(encoding="utf-8")
            self.assertIn("`wiki/index.md`", generated_index)
            self.assertIn("[Реестр фич](../features-index.md)", generated_index)
            self.assertIn("## Knowledge log", generated_index)
            self.assertIn("## Запись:", generated_log)

            lint_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "lint",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(lint_result.returncode, 0, lint_result.stdout)

            progress_after_lint = json.loads(progress_path.read_text(encoding="utf-8"))
            knowledge_lint_state = progress_after_lint["analysis_progress"]["validation"]["knowledge_lint"]
            self.assertEqual(knowledge_lint_state["status"], "completed")
            self.assertFalse(
                any(issue.startswith("ERROR:") for issue in knowledge_lint_state["issues"])
            )

    def test_compile_command_builds_wiki_layout_from_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            arch_repo_path = temp_path / "arch-repo"
            shutil.copytree(FIXTURES_ROOT / "valid_arch_repo", arch_repo_path)

            progress_path = temp_path / "repo-initialization-progress.json"
            init_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "init",
                    "--output",
                    str(progress_path),
                    "--product",
                    "AI CLI Gateway Service",
                    "--scope",
                    "full",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            compile_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "compile",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

            wiki_index_path = arch_repo_path / "wiki" / "index.md"
            wiki_log_path = arch_repo_path / "wiki" / "log.md"
            compile_report_path = arch_repo_path / "wiki" / "maps" / "compile-report.md"
            self.assertTrue(wiki_index_path.exists())
            self.assertTrue(wiki_log_path.exists())
            self.assertTrue(compile_report_path.exists())

            compiled_index = wiki_index_path.read_text(encoding="utf-8")
            compile_report = compile_report_path.read_text(encoding="utf-8")
            self.assertIn("[Аутентификация пользователя](../features/0001-user-authentication.md)", compiled_index)
            self.assertIn("[Интеграции gateway-service](../architecture/integrations/gateway-service.md)", compiled_index)
            self.assertIn("Missing related references: `не найдены`", compiled_index)
            self.assertIn("## Quality Gates", compiled_index)
            self.assertIn("Документов с frontmatter: `6`", compile_report)
            self.assertIn("## Coverage", compile_report)
            self.assertIn("Frontmatter coverage: `6/6` (100%)", compile_report)
            self.assertIn("Related metadata coverage: `6/6` (100%)", compile_report)
            self.assertIn("Weakly linked pages", compile_report)

            lint_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "lint",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(lint_result.returncode, 0, lint_result.stdout)

    def test_run_knowledge_lint_reports_stage7_consistency_issues(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            arch_repo_path = temp_path / "arch-repo"
            shutil.copytree(FIXTURES_ROOT / "valid_arch_repo", arch_repo_path)

            (arch_repo_path / "index.md").write_text(
                "# Navigation Redirect\n",
                encoding="utf-8",
            )
            wiki_dir = arch_repo_path / "wiki"
            wiki_dir.mkdir(parents=True, exist_ok=True)
            (wiki_dir / "index.md").write_text(
                "# Wiki Index\n\n- [Broken](../architecture/missing.md)\n",
                encoding="utf-8",
            )
            (arch_repo_path / "features-index.md").write_text(
                "# Реестр фич\n\n| Фича | Краткое описание | Основной файл |\n| --- | --- | --- |\n| `Auth` | `Login` | [feature](./features/missing.md) |\n",
                encoding="utf-8",
            )
            (arch_repo_path / "architecture" / "contracts" / "gateway-sync.yml").write_text(
                "service: gateway-service\n",
                encoding="utf-8",
            )
            (arch_repo_path / "glossary.md").write_text(
                "# Глоссарий\n\n- Кодовый путь: `src/app/page.tsx`\n",
                encoding="utf-8",
            )
            (wiki_dir / "log.md").write_text(
                "# Knowledge Log\n\n## Запись: 2026-07-03\n",
                encoding="utf-8",
            )
            (arch_repo_path / "open-questions.md").write_text(
                "# Открытые Вопросы\n\n| ID | Вопрос | Контекст | Связанный репозиторий | Статус | Нужен ответ пользователя | Что уже известно | Как закрыт или что нужно для закрытия |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| `Q-1` | `Как закрыт вопрос?` | `фича: auth` | `gateway-service` | `resolved` | `no` | `Не найдено` | `Закрыто без ссылки` |\n",
                encoding="utf-8",
            )
            (arch_repo_path / "architecture" / "hld.md").write_text(
                "---\nconfidence: maybe\nsources:\n  - gateway-service/src/api/auth.py\n---\n\n# HLD\n",
                encoding="utf-8",
            )

            issues = run_knowledge_lint(arch_repo_path)

            self.assertIn(
                "ERROR: wiki/index.md содержит битую ссылку на ../architecture/missing.md",
                issues,
            )
            self.assertIn(
                "ERROR: features-index.md ссылается на отсутствующий файл features/missing.md",
                issues,
            )
            self.assertIn(
                "ERROR: в architecture/contracts/gateway-sync.yml нет явной трассировки источников",
                issues,
            )
            self.assertIn(
                "ERROR: resolved-вопрос Q-1 в open-questions.md не ссылается на целевой артефакт",
                issues,
            )
            self.assertIn(
                "ERROR: ## Запись: 2026-07-03 не содержит содержимого",
                issues,
            )
            self.assertIn(
                "WARN: glossary.md содержит путь без явного префикса репозитория: src/app/page.tsx",
                issues,
            )
            self.assertIn(
                "ERROR: architecture/hld.md содержит неизвестное значение confidence `maybe`",
                issues,
            )

    def test_lint_reports_compile_quality_gate_and_required_section_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            arch_repo_path = temp_path / "arch-repo"
            shutil.copytree(FIXTURES_ROOT / "valid_arch_repo", arch_repo_path)

            progress_path = temp_path / "repo-initialization-progress.json"
            init_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "init",
                    "--output",
                    str(progress_path),
                    "--product",
                    "AI CLI Gateway Service",
                    "--scope",
                    "full",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            compile_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "compile",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

            for markdown_path in (
                arch_repo_path / "architecture" / "hld.md",
                arch_repo_path / "architecture" / "requirements.md",
                arch_repo_path / "architecture" / "security.md",
                arch_repo_path / "architecture" / "risks.md",
                arch_repo_path / "architecture" / "integrations" / "gateway-service.md",
            ):
                markdown_path.write_text(
                    markdown_path.read_text(encoding="utf-8").replace(
                        "related:\n",
                        "related_removed:\n",
                    ),
                    encoding="utf-8",
                )

            (arch_repo_path / "wiki" / "index.md").write_text(
                "# Wiki Index\n\n## Что читать первым\n",
                encoding="utf-8",
            )
            (arch_repo_path / "wiki" / "maps" / "compile-report.md").write_text(
                "# Compile Report\n\n## Summary\n",
                encoding="utf-8",
            )

            issues = run_knowledge_lint(arch_repo_path)

            self.assertIn(
                "ERROR: compile quality gate не пройден: related coverage 1/6 (17%) ниже порога 50%",
                issues,
            )
            self.assertIn(
                "ERROR: wiki/index.md не содержит обязательную секцию `## Артефакты по типам`",
                issues,
            )
            self.assertIn(
                "ERROR: wiki/maps/compile-report.md не содержит обязательную секцию `## Coverage`",
                issues,
            )

    def test_lint_reports_graph_drift_and_missing_closure_reflection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            arch_repo_path = temp_path / "arch-repo"
            shutil.copytree(FIXTURES_ROOT / "valid_arch_repo", arch_repo_path)

            progress_path = temp_path / "repo-initialization-progress.json"
            init_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "init",
                    "--output",
                    str(progress_path),
                    "--product",
                    "AI CLI Gateway Service",
                    "--scope",
                    "full",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(init_result.returncode, 0, init_result.stderr)

            compile_result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "compile",
                    "--progress",
                    str(progress_path),
                    "--arch-repo-path",
                    str(arch_repo_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

            (arch_repo_path / "wiki" / "index.md").write_text("# Drifted index\n", encoding="utf-8")
            (arch_repo_path / "features" / "0001-user-authentication.md").write_text(
                (arch_repo_path / "features" / "0001-user-authentication.md")
                .read_text(encoding="utf-8")
                .replace("`Q-1` — подтверждение выдачи CLI-токена вынесено в этот feature-артефакт.\n", ""),
                encoding="utf-8",
            )
            (arch_repo_path / "features" / "orphan-note.md").write_text(
                "---\n"
                "title: \"Orphan note\"\n"
                "type: concept\n"
                "sources:\n"
                "  - gateway-service/docs/orphan.md\n"
                "related: []\n"
                "created: \"2026-01-01\"\n"
                "updated: \"2026-01-01\"\n"
                "confidence: low\n"
                "domain: identity\n"
                "repositories:\n"
                "  - gateway-service\n"
                "---\n\n"
                "# Orphan note\n",
                encoding="utf-8",
            )

            issues = run_knowledge_lint(arch_repo_path)

            self.assertIn("ERROR: wiki/index.md не синхронизирован с compile output", issues)
            self.assertIn(
                "ERROR: resolved-вопрос Q-1 не отражён в артефакте features/0001-user-authentication.md",
                issues,
            )
            self.assertIn(
                "WARN: orphan page без входящих и исходящих ссылок: features/orphan-note.md",
                issues,
            )
            self.assertTrue(
                any(
                    issue.startswith("DEBT: low-confidence страница давно не обновлялась: features/orphan-note.md")
                    for issue in issues
                )
            )


class TemporalDeltaUnitTests(unittest.TestCase):
    def test_build_temporal_delta_marks_baseline_missing_for_empty_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "empty-repo"
            repo_path.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)

            repo: dict = {"main_branch": "main", "previous_analysis_target_commit": ""}
            _build_temporal_delta(repo, repo_path, "irrelevant-target-commit")

            self.assertEqual(repo["commit_range_status"], "baseline_missing")
            self.assertEqual(repo["window_start_commit"], "")
            self.assertEqual(repo["commit_range"], "")
            self.assertTrue(repo["temporal_delta_note"])

    def test_build_temporal_delta_marks_invalid_range_for_non_ancestor_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "rewritten-repo"
            commits = _create_git_repo_with_commits(
                repo_path,
                [("2021-01-01", "v1"), ("2021-02-01", "v2")],
            )
            first_commit, second_commit = commits

            # Simulate a rewritten history (force-push/rebase): amend the second commit so the
            # original second_commit is no longer an ancestor of the new HEAD.
            env = dict(os.environ)
            env["GIT_AUTHOR_DATE"] = "2021-03-01T12:00:00+00:00"
            env["GIT_COMMITTER_DATE"] = "2021-03-01T12:00:00+00:00"
            (repo_path / "payload.txt").write_text("v3-rewritten\n", encoding="utf-8")
            subprocess.run(["git", "add", "payload.txt"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "--amend", "-m", "commit-2-rewritten"],
                cwd=repo_path,
                check=True,
                capture_output=True,
                env=env,
            )
            new_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo_path, check=True, capture_output=True, text=True
            ).stdout.strip()

            repo: dict = {"main_branch": "main", "previous_analysis_target_commit": second_commit}
            _build_temporal_delta(repo, repo_path, new_head)

            self.assertEqual(repo["commit_range_status"], "invalid_range")
            self.assertEqual(repo["window_start_commit"], second_commit)
            self.assertEqual(repo["window_end_commit"], new_head)
            self.assertEqual(repo["commit_range"], "")
            self.assertIn("not an ancestor", repo["temporal_delta_note"])

    def test_build_temporal_delta_uses_previous_target_commit_as_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "linear-repo"
            commits = _create_git_repo_with_commits(
                repo_path,
                [("2021-01-01", "v1"), ("2021-02-01", "v2"), ("2021-03-01", "v3")],
            )
            first_commit, second_commit, third_commit = commits

            repo: dict = {"main_branch": "main", "previous_analysis_target_commit": first_commit}
            _build_temporal_delta(repo, repo_path, third_commit)

            self.assertEqual(repo["commit_range_status"], "diff_collected")
            self.assertEqual(repo["window_start_commit"], first_commit)
            self.assertEqual(repo["window_end_commit"], third_commit)
            self.assertEqual(repo["commit_range"], f"{first_commit}..{third_commit}")
            self.assertIn("payload.txt", repo["changed_paths"])

    def test_build_temporal_delta_parses_real_rename_and_delete_across_multiple_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir) / "rename-delete-repo"
            repo_path.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(
                ["git", "config", "user.name", "Codex Test"], cwd=repo_path, check=True, capture_output=True
            )
            subprocess.run(
                ["git", "config", "user.email", "codex@example.com"], cwd=repo_path, check=True, capture_output=True
            )

            def _commit(message: str) -> str:
                subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True, capture_output=True)
                return subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=repo_path, check=True, capture_output=True, text=True
                ).stdout.strip()

            (repo_path / "file_a.txt").write_text("a-1\n", encoding="utf-8")
            (repo_path / "file_b.txt").write_text("b-1\n", encoding="utf-8")
            subprocess.run(["git", "add", "file_a.txt", "file_b.txt"], cwd=repo_path, check=True, capture_output=True)
            baseline_commit = _commit("commit-1: baseline")

            (repo_path / "file_a.txt").write_text("a-2\n", encoding="utf-8")
            subprocess.run(["git", "add", "file_a.txt"], cwd=repo_path, check=True, capture_output=True)
            _commit("commit-2: modify file_a")

            subprocess.run(
                ["git", "mv", "file_b.txt", "file_b_renamed.txt"], cwd=repo_path, check=True, capture_output=True
            )
            _commit("commit-3: rename file_b")

            subprocess.run(["git", "rm", "file_a.txt"], cwd=repo_path, check=True, capture_output=True)
            target_commit = _commit("commit-4: delete file_a")

            repo: dict = {"main_branch": "main", "previous_analysis_target_commit": baseline_commit}
            _build_temporal_delta(repo, repo_path, target_commit)

            self.assertEqual(repo["commit_range_status"], "diff_collected")
            self.assertEqual(repo["commit_range"], f"{baseline_commit}..{target_commit}")
            self.assertEqual(repo["changed_paths"], ["file_b_renamed.txt"])
            self.assertEqual(repo["renamed_paths"], ["file_b.txt -> file_b_renamed.txt"])
            self.assertEqual(repo["deleted_paths"], ["file_a.txt"])
            log_lines = [line for line in repo["commit_log_summary"].splitlines() if line.strip()]
            self.assertEqual(len(log_lines), 3)
            self.assertTrue(any("commit-4" in line for line in log_lines))
            self.assertTrue(any("commit-3" in line for line in log_lines))
            self.assertTrue(any("commit-2" in line for line in log_lines))


if __name__ == "__main__":
    unittest.main()
