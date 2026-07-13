"""Structural and cross-artifact validation for architecture/* knowledge artifacts.

Mirrors the lint pattern in knowledge_runtime.py, but targets architecture/*
instead of the wiki layer. This is where the "Автоматические проверки" promised
in checklist-architecture-artifact-updates.md are actually enforced — the
worker prompt used to tell the agent to shell out to a CLI script
(scripts/analysis_guard.py) that does not exist inside this service.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema
import yaml
from openapi_spec_validator import validate as validate_openapi
from openapi_spec_validator.exceptions import OpenAPISpecValidatorError
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS: Final[dict[str, tuple[str, ...]]] = {
    "architecture/hld.md": (
        "## Обзор текущей архитектуры",
        "## Контекстная диаграмма",
        "## Компоненты",
        "## Основные потоки",
        "## Интеграции",
        "## Риски и пробелы",
        "## Примечания по достоверности",
        "## Трассировка источников по разделам",
    ),
    "architecture/security.md": (
        "## Аутентификация пользователей и внешних клиентов",
        "## Межсервисное доверие",
        "## Границы доверия",
        "## Чувствительные данные",
        "## Примечания по достоверности",
        "## Закрытые вопросы",
    ),
    "architecture/risks.md": ("## Категории",),
    "architecture/tech-stack.md": ("## Правила заполнения", "## Таблица", "## Примечания"),
    "architecture/roles-and-permissions.md": ("## Роли", "## Матрица доступа к функционалу"),
    "architecture/domain-entities.md": ("## Расхождения и открытые вопросы", "## Источники подтверждения"),
    "architecture/integrations-overview.md": (
        "## Границы описания",
        "## Карта интеграций",
        "## Разрез по направлению",
        "## Основные потоки данных",
        "## Аутентификация и границы доверия",
        "## Примечания по надёжности",
        "## Наблюдаемость",
        "## Пробелы и открытые вопросы",
    ),
    "architecture/constraints.md": ("## Подтвержденные ограничения", "## Выведенные ограничения"),
    "architecture/requirements.md": (
        "## Наблюдаемые функциональные требования",
        "## Наблюдаемые или выведенные нефункциональные требования",
        "## Примечания по достоверности",
    ),
}


def lint_architecture_artifacts(arch_repo_path: Path) -> list[str]:
    issues: list[str] = []
    for relative_path, required_sections in ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS.items():
        issues.extend(_lint_required_sections(arch_repo_path, relative_path, required_sections))
    issues.extend(_lint_agents_md(arch_repo_path))
    issues.extend(_lint_directory_documents(arch_repo_path, "architecture/integrations", INTEGRATION_REQUIRED_SECTIONS))
    issues.extend(_lint_directory_documents(arch_repo_path, "features", FEATURE_REQUIRED_SECTIONS))
    issues.extend(_lint_contracts(arch_repo_path))
    issues.extend(_lint_storage(arch_repo_path))
    issues.extend(_lint_commit_consistency(arch_repo_path))
    return issues


def _lint_required_sections(
    arch_repo_path: Path,
    relative_path: str,
    required_sections: tuple[str, ...],
) -> list[str]:
    artifact_path = arch_repo_path / relative_path
    if not artifact_path.exists():
        return [f"ERROR: отсутствует {relative_path}"]

    content = artifact_path.read_text(encoding="utf-8")
    return [
        f"ERROR: {relative_path} не содержит обязательную секцию `{section}`"
        for section in required_sections
        if section not in content
    ]


AGENTS_REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Что читать первым",
    "## Source of Truth",
    "## Структура репозитория",
    "## Operations",
    "## Правила трассировки и gaps",
    "## С чего начинать по типу задачи",
    "## Текущие сервисы",
    "## Как добавлять изменения",
)


def _lint_agents_md(arch_repo_path: Path) -> list[str]:
    agents_path = arch_repo_path / "AGENTS.md"
    if not agents_path.exists():
        return []

    content = agents_path.read_text(encoding="utf-8")
    return [
        f"ERROR: AGENTS.md не содержит обязательную секцию `{section}`"
        for section in AGENTS_REQUIRED_SECTIONS
        if section not in content
    ]


INTEGRATION_REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Краткое описание сервиса",
    "## Входящие интеграции",
    "## Исходящие интеграции",
    "## Сводка по данным и границам доверия",
    "## Итоговые выводы",
    "## Закрытые вопросы",
    "## Трассировка источников по разделам",
)

FEATURE_REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Метаданные",
    "## Бизнес-возможность",
    "## Текущее поведение",
    "## Функциональные правила",
    "## Основной поток",
    "## Трассировка реализации",
    "## Примечания по достоверности",
    "## Трассировка источников по разделам",
)


def _lint_directory_documents(
    arch_repo_path: Path,
    relative_dir: str,
    required_sections: tuple[str, ...],
) -> list[str]:
    directory = arch_repo_path / relative_dir
    if not directory.exists():
        return []

    issues: list[str] = []
    for markdown_path in sorted(directory.glob("*.md")):
        label = markdown_path.relative_to(arch_repo_path).as_posix()
        content = markdown_path.read_text(encoding="utf-8")
        issues.extend(
            f"ERROR: {label} не содержит обязательную секцию `{section}`"
            for section in required_sections
            if section not in content
        )
    return issues


_ASYNCAPI_SCHEMA_PATH: Final[Path] = Path(__file__).parent / "schemas" / "asyncapi-2.6.0.json"
_asyncapi_schema_cache: dict[str, Any] | None = None


def _get_asyncapi_schema() -> dict[str, Any]:
    global _asyncapi_schema_cache  # noqa: PLW0603
    if _asyncapi_schema_cache is None:
        _asyncapi_schema_cache = json.loads(_ASYNCAPI_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _asyncapi_schema_cache


def _lint_contracts(arch_repo_path: Path) -> list[str]:
    contracts_dir = arch_repo_path / "architecture" / "contracts"
    if not contracts_dir.exists():
        return []

    issues: list[str] = []
    contract_paths = sorted(contracts_dir.glob("*.yml")) + sorted(contracts_dir.glob("*.yaml"))
    for contract_path in contract_paths:
        issues.extend(_lint_single_contract(contract_path, arch_repo_path))
    return issues


def _lint_single_contract(contract_path: Path, arch_repo_path: Path) -> list[str]:
    label = contract_path.relative_to(arch_repo_path).as_posix()
    try:
        document = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"ERROR: {label} невалидный YAML: {error}"]

    if not isinstance(document, dict):
        return [f"ERROR: {label} невалидный контракт: ожидается mapping верхнего уровня"]

    if "openapi" in document:
        return _lint_openapi_contract(document, label)
    if "asyncapi" in document:
        return _lint_asyncapi_contract(document, label)

    return [
        f"ERROR: {label} не является OpenAPI/AsyncAPI контрактом: "
        "отсутствует ключ верхнего уровня `openapi` или `asyncapi`"
    ]


def _lint_openapi_contract(document: dict[str, Any], label: str) -> list[str]:
    try:
        validate_openapi(document)
    except (OpenAPISpecValidatorError, OpenAPIValidationError) as error:
        first_line = str(error).strip().splitlines()[0]
        return [f"ERROR: {label} не проходит валидацию openapi-spec-validator: {first_line}"]
    return []


def _lint_asyncapi_contract(document: dict[str, Any], label: str) -> list[str]:
    try:
        jsonschema.validate(document, _get_asyncapi_schema())
    except jsonschema.exceptions.ValidationError as error:
        first_line = str(error).strip().splitlines()[0]
        return [f"ERROR: {label} не проходит валидацию AsyncAPI 2.6.0 JSON Schema: {first_line}"]
    return []


def _lint_storage(arch_repo_path: Path) -> list[str]:
    storage_dir = arch_repo_path / "architecture" / "storage"
    if not storage_dir.exists():
        return []

    issues: list[str] = []
    for storage_path in sorted(storage_dir.glob("*.yml")):
        label = storage_path.relative_to(arch_repo_path).as_posix()
        try:
            document = yaml.safe_load(storage_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            issues.append(f"ERROR: {label} невалидный YAML: {error}")
            continue

        storage_section = document.get("storage") if isinstance(document, dict) else None
        if not isinstance(storage_section, dict):
            issues.append(f"ERROR: {label} не содержит mapping верхнего уровня `storage`")
            continue
        if not storage_section.get("type"):
            issues.append(f"ERROR: {label} не содержит `storage.type`")
    return issues


def _load_yaml_document(document_path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        document = yaml.safe_load(document_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return None, [f"ERROR: {label} невалидный YAML: {error}"]

    if not isinstance(document, dict):
        return None, [f"ERROR: {label} невалидный формат: ожидается mapping верхнего уровня"]

    return document, []


def _lint_commit_consistency(arch_repo_path: Path) -> list[str]:
    landscape_path = arch_repo_path / "architecture" / "landscape.yaml"
    if not landscape_path.exists():
        return []

    landscape, issues = _load_yaml_document(landscape_path, "architecture/landscape.yaml")
    if issues:
        return issues
    if landscape is None:
        return []

    entities = landscape.get("entities") or {}
    services = entities.get("services") if isinstance(entities, dict) else None
    if services is None:
        return []
    if not isinstance(services, list):
        return ["ERROR: architecture/landscape.yaml: entities.services должен быть списком"]

    structure_dir = arch_repo_path / "architecture" / "structure"
    return [
        issue
        for service in services
        for issue in _lint_service_commit_consistency(service, structure_dir)
    ]


def _lint_service_commit_consistency(service: object, structure_dir: Path) -> list[str]:
    issues: list[str] = []
    if isinstance(service, dict):
        service_id = _normalize_service_value(service.get("id") or service.get("name"))
        repository_state = service.get("repository_state") or {}
        head_commit = _normalize_service_value(
            repository_state.get("head_commit") if isinstance(repository_state, dict) else "",
        )
        if service_id and head_commit:
            structure_path = structure_dir / f"{service_id}.yml"
            label = f"architecture/structure/{service_id}.yml"
            if not structure_path.exists():
                issues.append(f"ERROR: {label} не найден для сервиса `{service_id}` из landscape.yaml")
            else:
                structure_document, issues = _load_yaml_document(structure_path, label)
                if not issues and structure_document is not None:
                    repo_structure_map = structure_document.get("repo_structure_map") or {}
                    analyzed_commit = _normalize_service_value(
                        repo_structure_map.get("analyzed_commit") if isinstance(repo_structure_map, dict) else "",
                    )
                    if analyzed_commit and analyzed_commit != head_commit:
                        issues.append(
                            f"ERROR: рассинхронизация commit между landscape.yaml (head_commit=`{head_commit}`) и "
                            f"{label} (analyzed_commit=`{analyzed_commit}`) для сервиса `{service_id}`"
                        )
    return issues


def _normalize_service_value(value: object) -> str:
    return str(value).strip() if value else ""
