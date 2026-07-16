from app.workflows.init_arch.domain import CommitRangeStatus, RepositoryExecution
from app.workflows.init_arch.domain.signal_routing import (
    DiffSeverity,
    classify_diff_severity,
    route_checklist_items,
)

_ALL_ITEMS = [
    "repository_classification",
    "entrypoints_and_interfaces",
    "business_flow_orchestration",
    "configs_and_runtime",
    "contracts_and_schemas",
    "data_and_storage",
    "domain_entities",
    "integrations_and_dependencies",
    "roles_and_permissions_updates",
    "security_and_auth_updates",
    "deployment_and_operability",
    "architecture_artifact_updates",
    "repository_consistency_review",
]


def _make_repo(**kwargs) -> RepositoryExecution:
    return RepositoryExecution(repository_name="svc-a", **kwargs)


class TestClassifyDiffSeverity:
    def test_not_started_requires_full_analysis(self):
        repo = _make_repo(commit_range_status=CommitRangeStatus.NOT_STARTED)
        assert classify_diff_severity(repo) is DiffSeverity.FULL_REQUIRED

    def test_baseline_missing_requires_full_analysis(self):
        repo = _make_repo(commit_range_status=CommitRangeStatus.BASELINE_MISSING)
        assert classify_diff_severity(repo) is DiffSeverity.FULL_REQUIRED

    def test_invalid_range_requires_full_analysis(self):
        repo = _make_repo(commit_range_status=CommitRangeStatus.INVALID_RANGE)
        assert classify_diff_severity(repo) is DiffSeverity.FULL_REQUIRED

    def test_no_changes_is_no_signal(self):
        repo = _make_repo(commit_range_status=CommitRangeStatus.NO_CHANGES)
        assert classify_diff_severity(repo) is DiffSeverity.NO_SIGNAL

    def test_diff_collected_without_paths_is_no_signal(self):
        repo = _make_repo(commit_range_status=CommitRangeStatus.DIFF_COLLECTED)
        assert classify_diff_severity(repo) is DiffSeverity.NO_SIGNAL

    def test_diff_collected_with_narrow_footprint_is_local(self):
        repo = _make_repo(
            commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
            changed_paths=["app/api/routers/users.py", "app/api/schemas/user.py"],
        )
        assert classify_diff_severity(repo) is DiffSeverity.LOCAL

    def test_diff_collected_with_wide_footprint_is_broad(self):
        repo = _make_repo(
            commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
            changed_paths=["app/a.py", "lib/b.py", "tests/c.py", "docs/d.md", "infra/e.tf"],
        )
        assert classify_diff_severity(repo) is DiffSeverity.BROAD

    def test_renamed_and_deleted_paths_count_towards_footprint(self):
        repo = _make_repo(
            commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
            renamed_paths=["a/x.py"],
            deleted_paths=["b/y.py", "c/z.py", "d/w.py"],
        )
        assert classify_diff_severity(repo) is DiffSeverity.BROAD


class TestRouteChecklistItems:
    def test_full_required_returns_all_items(self):
        repo = _make_repo(commit_range_status=CommitRangeStatus.NOT_STARTED)
        assert route_checklist_items(repo, all_checklist_item_ids=_ALL_ITEMS) == _ALL_ITEMS

    def test_broad_returns_all_items(self):
        repo = _make_repo(
            commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
            changed_paths=["app/a.py", "lib/b.py", "tests/c.py", "docs/d.md", "infra/e.tf"],
        )
        assert route_checklist_items(repo, all_checklist_item_ids=_ALL_ITEMS) == _ALL_ITEMS

    def test_no_signal_routes_only_consistency_review(self):
        repo = _make_repo(commit_range_status=CommitRangeStatus.NO_CHANGES)
        assert route_checklist_items(repo, all_checklist_item_ids=_ALL_ITEMS) == ["repository_consistency_review"]

    def test_local_routes_impacted_categories_plus_always_routed(self):
        repo = _make_repo(
            commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
            changed_paths=["app/api/routers/users.py", "app/api/schemas/user.py"],
        )
        routed = route_checklist_items(repo, all_checklist_item_ids=_ALL_ITEMS)
        assert "entrypoints_and_interfaces" in routed
        assert "contracts_and_schemas" in routed
        assert "architecture_artifact_updates" in routed
        assert "repository_consistency_review" in routed
        assert "data_and_storage" not in routed
        assert "roles_and_permissions_updates" not in routed

    def test_local_preserves_input_order(self):
        repo = _make_repo(
            commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
            changed_paths=["app/auth/permissions.py"],
        )
        routed = route_checklist_items(repo, all_checklist_item_ids=_ALL_ITEMS)
        assert routed == [item for item in _ALL_ITEMS if item in set(routed)]

    def test_local_with_unmatched_paths_routes_only_always_routed(self):
        repo = _make_repo(
            commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
            changed_paths=["README.md"],
        )
        routed = route_checklist_items(repo, all_checklist_item_ids=_ALL_ITEMS)
        assert routed == ["architecture_artifact_updates", "repository_consistency_review"]
