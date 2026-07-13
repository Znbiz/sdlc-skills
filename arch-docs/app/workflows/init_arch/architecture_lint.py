"""Structural and cross-artifact validation for architecture/* knowledge artifacts.

Mirrors the lint pattern in knowledge_runtime.py, but targets architecture/*
instead of the wiki layer. This is where the "Автоматические проверки" promised
in checklist-architecture-artifact-updates.md are actually enforced — the
worker prompt used to tell the agent to shell out to a CLI script
(scripts/analysis_guard.py) that does not exist inside this service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

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
