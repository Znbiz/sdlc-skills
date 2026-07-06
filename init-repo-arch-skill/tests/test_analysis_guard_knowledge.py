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

from analysis_guard.knowledge import run_knowledge_lint  # noqa: E402


class AnalysisGuardKnowledgeTests(unittest.TestCase):
    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def _create_git_repo_with_commits(self, repo_path: Path, commits: list[tuple[str, str]]) -> list[str]:
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
            self.assertEqual(historical_after_advance["completed_snapshot_dates"], ["2021-04-15"])

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


if __name__ == "__main__":
    unittest.main()
