"""Argument parser and entry point."""

from __future__ import annotations

import argparse

from .commands import (
    advance_command,
    cascade_command,
    init_command,
    repo_command,
    signal_command,
    status_command,
    validate_command,
    validate_commits_command,
)
from .definitions import DIFF_CLASSIFICATIONS, ITEM_STATUSES, SIGNAL_CATEGORY_INDEX


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Guard rails for update-repo-arch-skill workflow. "
            "Превращает дельта-обновление архитектурной документации в явную "
            "state machine: triage репозиториев, сигнальный роутинг, точечный "
            "разбор по категориям и каскадные эффекты."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------
    init_parser = subparsers.add_parser(
        "init", help="Создать новый progress-файл прогона обновления"
    )
    init_parser.add_argument("--output", required=True, help="Путь к создаваемому progress-файлу (JSON)")
    init_parser.add_argument(
        "--arch-repo-path", required=True, help="Путь к существующему архитектурному репозиторию"
    )
    init_parser.add_argument("--analyst", default="codex", help="Идентификатор аналитика")
    init_parser.add_argument("--force", action="store_true", help="Перезаписать существующий progress-файл")
    init_parser.set_defaults(func=init_command)

    # ------------------------------------------------------------------
    # validate / status
    # ------------------------------------------------------------------
    validate_parser = subparsers.add_parser("validate", help="Проверить целостность progress-файла")
    validate_parser.add_argument("--progress", required=True, help="Путь к progress-файлу (JSON)")
    validate_parser.set_defaults(func=validate_command)

    status_parser = subparsers.add_parser("status", help="Вывести текущий статус workflow")
    status_parser.add_argument("--progress", required=True, help="Путь к progress-файлу (JSON)")
    status_parser.set_defaults(func=status_command)

    # ------------------------------------------------------------------
    # repo
    # ------------------------------------------------------------------
    repo_parser = subparsers.add_parser(
        "repo",
        help="Единая команда для операций с репозиторием: --register/--start/--set-diff/--complete",
    )
    repo_parser.add_argument("--progress", required=True, help="Путь к progress-файлу (JSON)")
    repo_parser.add_argument("--name", required=True, help="Имя репозитория")
    repo_parser.add_argument("--notes", help="Произвольная заметка к операции")
    repo_parser.add_argument("--register", action="store_true", help="Зарегистрировать репозиторий")
    repo_parser.add_argument("--start", action="store_true", help="Начать работу с репозиторием")
    repo_parser.add_argument(
        "--set-diff", action="store_true", help="Зафиксировать классификацию дельты репозитория"
    )
    repo_parser.add_argument("--complete", action="store_true", help="Завершить работу с репозиторием")
    # --register fields
    repo_parser.add_argument("--repository-url", help="URL репозитория (git remote)")
    repo_parser.add_argument("--local-path", default="", help="Локальный путь к клону репозитория")
    repo_parser.add_argument("--main-branch", default="", help="Основная ветка репозитория")
    repo_parser.add_argument(
        "--previous-baseline-commit", default="", help="Commit SHA из прошлого анализа (baseline)"
    )
    repo_parser.add_argument(
        "--position", choices=["append", "prepend"], default="append",
        help="Куда добавить репозиторий в ordered_repository_names",
    )
    # --set-diff fields
    repo_parser.add_argument("--classification", choices=DIFF_CLASSIFICATIONS, help="none|minor|significant")
    repo_parser.add_argument("--new-baseline-commit", help="Commit SHA после обновления до HEAD")
    repo_parser.add_argument("--stat-summary", help="Краткое summary git diff --stat")
    repo_parser.add_argument("--commit-log-summary", help="Краткое summary git log --oneline")
    repo_parser.add_argument(
        "--baseline-invalid", action="store_true",
        help="previous_baseline_commit не найден в истории (force-push/rebase)",
    )
    repo_parser.add_argument("--allow-dirty", action="store_true", help="Игнорировать ошибки валидации")
    repo_parser.set_defaults(func=repo_command)

    # ------------------------------------------------------------------
    # signal
    # ------------------------------------------------------------------
    signal_parser = subparsers.add_parser(
        "signal", help="Управление категориями сигналов (signal_categories) репозитория"
    )
    signal_parser.add_argument("--progress", required=True, help="Путь к progress-файлу (JSON)")
    signal_parser.add_argument("--repo", required=True, help="Имя репозитория")
    signal_parser.add_argument(
        "--category", required=True, choices=sorted(SIGNAL_CATEGORY_INDEX), help="Идентификатор категории"
    )
    signal_parser.add_argument(
        "--add-category", action="store_true", help="Зарегистрировать новую категорию для репозитория"
    )
    signal_parser.add_argument("--source-paths", help="Изменившиеся пути, через запятую")
    signal_parser.add_argument(
        "--status", choices=ITEM_STATUSES, default="completed", help="Новый статус категории"
    )
    signal_parser.add_argument("--notes", help="Заметка к категории (что обновлено)")
    signal_parser.set_defaults(func=signal_command)

    # ------------------------------------------------------------------
    # cascade
    # ------------------------------------------------------------------
    cascade_parser = subparsers.add_parser(
        "cascade", help="Управление каскадными эффектами между репозиториями/артефактами"
    )
    cascade_parser.add_argument("--progress", required=True, help="Путь к progress-файлу (JSON)")
    cascade_parser.add_argument("--source-repo", required=True, help="Репозиторий-источник изменения")
    cascade_parser.add_argument("--target", required=True, help="Целевой репозиторий или артефакт")
    cascade_parser.add_argument("--register", action="store_true", help="Зарегистрировать каскадный эффект")
    cascade_parser.add_argument("--complete", action="store_true", help="Закрыть каскадный эффект")
    cascade_parser.add_argument("--reason", help="Почему цель может быть затронута")
    cascade_parser.add_argument("--notes", help="Что проверено / что обновлено / пометка 'вне scope'")
    cascade_parser.set_defaults(func=cascade_command)

    # ------------------------------------------------------------------
    # advance
    # ------------------------------------------------------------------
    advance_parser = subparsers.add_parser(
        "advance", help="Завершить текущий шаг workflow и перейти к следующему"
    )
    advance_parser.add_argument("--progress", required=True, help="Путь к progress-файлу (JSON)")
    advance_parser.add_argument("--step", help="Явное указание завершаемого шага (защита от пропуска)")
    advance_parser.add_argument("--note", help="Заметка к завершённому шагу")
    advance_parser.add_argument("--repository", help="Обновить current_position.current_repository")
    advance_parser.add_argument("--resume-hint", help="Подсказка для возобновления работы")
    advance_parser.add_argument("--allow-dirty", action="store_true", help="Игнорировать ошибки валидации")
    advance_parser.set_defaults(func=advance_command)

    # ------------------------------------------------------------------
    # validate-commits — сверить commit в landscape.yaml и structure/<repo>.yml
    # ------------------------------------------------------------------
    commits_parser = subparsers.add_parser(
        "validate-commits",
        help=(
            "Проверить, что landscape.yaml repository_state.head_commit совпадает с "
            "architecture/structure/<repo>.yml analyzed_commit для каждого сервиса"
        ),
    )
    commits_parser.add_argument(
        "--arch-repo-path",
        required=True,
        help="Путь к корню архитектурного репозитория (содержит architecture/landscape.yaml)",
    )
    commits_parser.set_defaults(func=validate_commits_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
