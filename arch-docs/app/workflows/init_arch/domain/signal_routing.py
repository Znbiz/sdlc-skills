from __future__ import annotations

import enum
import typing

from app.workflows.init_arch.domain.models import CommitRangeStatus, RepositoryExecution

_LOCAL_DIFF_MAX_TOP_LEVEL_DIRS: typing.Final[int] = 3
_NO_SIGNAL_CONFIRMATION_ITEM: typing.Final[str] = "repository_consistency_review"
_ALWAYS_ROUTED_CHECKLIST_ITEMS: typing.Final[frozenset[str]] = frozenset(
    {"architecture_artifact_updates", "repository_consistency_review"}
)

_PATH_SIGNAL_CATEGORIES: typing.Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("migrations/", ("data_and_storage",)),
    (".sql", ("data_and_storage",)),
    ("models/", ("data_and_storage", "domain_entities")),
    ("entities/", ("domain_entities", "data_and_storage")),
    ("api/", ("entrypoints_and_interfaces", "contracts_and_schemas")),
    ("routers/", ("entrypoints_and_interfaces",)),
    ("controllers/", ("entrypoints_and_interfaces",)),
    ("handlers/", ("entrypoints_and_interfaces",)),
    ("endpoints/", ("entrypoints_and_interfaces", "contracts_and_schemas")),
    ("resolvers/", ("entrypoints_and_interfaces", "contracts_and_schemas")),
    ("serializers/", ("contracts_and_schemas",)),
    ("schemas/", ("contracts_and_schemas",)),
    ("dto/", ("contracts_and_schemas",)),
    ("consumers/", ("integrations_and_dependencies", "contracts_and_schemas")),
    ("producers/", ("integrations_and_dependencies",)),
    ("events/", ("integrations_and_dependencies", "contracts_and_schemas")),
    ("services/", ("business_flow_orchestration",)),
    ("workflows/", ("business_flow_orchestration",)),
    ("usecases/", ("business_flow_orchestration",)),
    ("orchestrators/", ("business_flow_orchestration",)),
    ("clients/", ("integrations_and_dependencies", "tech_stack_collection")),
    ("external/", ("integrations_and_dependencies",)),
    ("integrations/", ("integrations_and_dependencies",)),
    ("config/", ("configs_and_runtime",)),
    ("settings.py", ("configs_and_runtime",)),
    ("docker-compose", ("configs_and_runtime", "deployment_and_operability")),
    ("dockerfile", ("configs_and_runtime", "deployment_and_operability")),
    (".github/workflows/", ("deployment_and_operability",)),
    ("helm/", ("deployment_and_operability",)),
    ("k8s/", ("deployment_and_operability",)),
    ("terraform/", ("deployment_and_operability",)),
    ("auth/", ("roles_and_permissions_updates", "security_and_auth_updates")),
    ("permissions/", ("roles_and_permissions_updates",)),
    ("rbac/", ("roles_and_permissions_updates", "security_and_auth_updates")),
    ("acl/", ("roles_and_permissions_updates",)),
    ("tests/", ("tests_and_behavior_evidence",)),
    ("pyproject.toml", ("tech_stack_collection",)),
    ("package.json", ("tech_stack_collection",)),
    ("requirements", ("tech_stack_collection",)),
    ("go.mod", ("tech_stack_collection",)),
)


class DiffSeverity(str, enum.Enum):
    FULL_REQUIRED = "full_required"
    NO_SIGNAL = "no_signal"
    LOCAL = "local"
    BROAD = "broad"


def _touched_paths(repository: RepositoryExecution) -> list[str]:
    return [*repository.changed_paths, *repository.renamed_paths, *repository.deleted_paths]


def classify_diff_severity(repository: RepositoryExecution) -> DiffSeverity:
    status = repository.commit_range_status
    if status in (
        CommitRangeStatus.NOT_STARTED,
        CommitRangeStatus.BASELINE_MISSING,
        CommitRangeStatus.INVALID_RANGE,
    ):
        return DiffSeverity.FULL_REQUIRED
    if status is CommitRangeStatus.NO_CHANGES:
        return DiffSeverity.NO_SIGNAL

    touched_paths = _touched_paths(repository)
    if not touched_paths:
        return DiffSeverity.NO_SIGNAL

    top_level_dirs = {path.split("/", 1)[0] for path in touched_paths}
    if len(top_level_dirs) <= _LOCAL_DIFF_MAX_TOP_LEVEL_DIRS:
        return DiffSeverity.LOCAL
    return DiffSeverity.BROAD


def _categories_for_path(path: str) -> frozenset[str]:
    lowered = path.lower()
    categories: set[str] = set()
    for pattern, category_ids in _PATH_SIGNAL_CATEGORIES:
        if pattern in lowered:
            categories.update(category_ids)
    return frozenset(categories)


def route_checklist_items(repository: RepositoryExecution, *, all_checklist_item_ids: list[str]) -> list[str]:
    """Prioritize the checklist by diff severity of the current temporal window.

    Does not replace a full-state analysis: `full_required`/`broad` always return the
    full checklist, `local`/`no_signal` only narrow the depth for one repository-window.
    """
    severity = classify_diff_severity(repository)
    if severity in (DiffSeverity.FULL_REQUIRED, DiffSeverity.BROAD):
        return list(all_checklist_item_ids)
    if severity is DiffSeverity.NO_SIGNAL:
        return [item_id for item_id in all_checklist_item_ids if item_id == _NO_SIGNAL_CONFIRMATION_ITEM]

    routed_categories: set[str] = set(_ALWAYS_ROUTED_CHECKLIST_ITEMS)
    for path in _touched_paths(repository):
        routed_categories.update(_categories_for_path(path))
    return [item_id for item_id in all_checklist_item_ids if item_id in routed_categories]
