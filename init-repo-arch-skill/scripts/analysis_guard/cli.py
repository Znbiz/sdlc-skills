"""Argument parser and entry point."""

from __future__ import annotations

import argparse

from .commands import (
    advance_command,
    domain_command,
    init_command,
    repo_command,
    status_command,
    validate_command,
    validate_contracts_command,
)
from .definitions import CHECKLIST_INDEX


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Guard rails for init-repo-arch-skill workflow. "
            "Превращает workflow анализа в явную state machine: "
            "инициализирует progress-файл, печатает статус, валидирует переходы "
            "и продвигает шаги по одному."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ------------------------------------------------------------------
    # init — создать новый progress-файл
    # ------------------------------------------------------------------
    init_parser = subparsers.add_parser(
        "init",
        help="Создать новый progress-файл с начальным состоянием workflow",
    )
    init_parser.add_argument(
        "--output",
        required=True,
        help="Путь к создаваемому progress-файлу (JSON)",
    )
    init_parser.add_argument(
        "--product",
        required=True,
        help="Название продукта / системы, которую анализируем",
    )
    init_parser.add_argument(
        "--scope",
        required=True,
        help="Контур анализа (например: 'full', 'backend-only', 'payments domain')",
    )
    init_parser.add_argument(
        "--analyst",
        default="codex",
        help="Идентификатор аналитика (по умолчанию: codex)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать progress-файл, если он уже существует",
    )
    init_parser.set_defaults(func=init_command)

    # ------------------------------------------------------------------
    # validate — проверить целостность progress-файла
    # ------------------------------------------------------------------
    validate_parser = subparsers.add_parser(
        "validate",
        help="Проверить целостность workflow: порядок шагов, обязательные prerequisites",
    )
    validate_parser.add_argument(
        "--progress",
        required=True,
        help="Путь к progress-файлу (JSON)",
    )
    validate_parser.set_defaults(func=validate_command)

    # ------------------------------------------------------------------
    # status — вывести компактный статус workflow
    # ------------------------------------------------------------------
    status_parser = subparsers.add_parser(
        "status",
        help="Вывести текущий статус workflow, репозиториев и открытых вопросов",
    )
    status_parser.add_argument(
        "--progress",
        required=True,
        help="Путь к progress-файлу (JSON)",
    )
    status_parser.set_defaults(func=status_command)

    # ------------------------------------------------------------------
    # repo — единая команда для всех операций с репозиторием
    # ------------------------------------------------------------------
    repo_parser = subparsers.add_parser(
        "repo",
        help=(
            "Единая команда для работы с репозиторием: "
            "--register, --start, --checklist-item или --complete"
        ),
    )
    repo_parser.add_argument(
        "--progress",
        required=True,
        help="Путь к progress-файлу (JSON)",
    )
    repo_parser.add_argument(
        "--name",
        required=True,
        help="Имя репозитория (должно совпадать с именем при регистрации)",
    )
    repo_parser.add_argument(
        "--notes",
        help="Произвольная заметка к операции",
    )
    # действия (ровно одно из четырёх)
    repo_parser.add_argument(
        "--register",
        action="store_true",
        help="Зарегистрировать репозиторий в progress-файле",
    )
    repo_parser.add_argument(
        "--start",
        action="store_true",
        help="Начать анализ репозитория (только во время шага analyze_repositories)",
    )
    repo_parser.add_argument(
        "--complete",
        action="store_true",
        help="Завершить анализ репозитория; требует заполненных main_branch и commit-полей",
    )
    repo_parser.add_argument(
        "--checklist-item",
        choices=sorted(CHECKLIST_INDEX),
        help="Идентификатор элемента чеклиста для обновления",
    )
    repo_parser.add_argument(
        "--checklist-status",
        choices=["not_started", "in_progress", "completed", "blocked"],
        default="completed",
        help="Новый статус элемента чеклиста (по умолчанию: completed)",
    )
    # поля для --register
    repo_parser.add_argument(
        "--role",
        help="Роль репозитория в системе (например: backend-api, frontend, infra)",
    )
    repo_parser.add_argument(
        "--repository-url",
        help="URL репозитория (git remote)",
    )
    repo_parser.add_argument(
        "--source-type",
        default="temp_clone",
        help="Способ получения кода: temp_clone | local_path (по умолчанию: temp_clone)",
    )
    repo_parser.add_argument(
        "--local-path",
        default="",
        help="Локальный путь к клону репозитория (если source-type=local_path)",
    )
    repo_parser.add_argument(
        "--main-branch",
        default="",
        help="Основная ветка репозитория (main, master, …)",
    )
    repo_parser.add_argument(
        "--remote-status",
        default="не удалось проверить",
        help="Статус доступности remote (по умолчанию: 'не удалось проверить')",
    )
    repo_parser.add_argument(
        "--position",
        choices=["append", "prepend"],
        default="append",
        help="Куда добавить репозиторий в ordered_repository_names (по умолчанию: append)",
    )
    repo_parser.add_argument(
        "--in-scope",
        action="store_true",
        default=True,
        help="Пометить репозиторий как in-scope (по умолчанию: True)",
    )
    repo_parser.add_argument(
        "--requested-from-user",
        action="store_true",
        default=True,
        help="Репозиторий получен от пользователя, а не обнаружен автоматически",
    )
    repo_parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Продолжить даже при наличии ошибок валидации progress-файла",
    )
    repo_parser.set_defaults(func=repo_command)

    # ------------------------------------------------------------------
    # advance — завершить текущий шаг и перейти к следующему
    # ------------------------------------------------------------------
    advance_parser = subparsers.add_parser(
        "advance",
        help="Завершить текущий шаг workflow и автоматически перейти к следующему",
    )
    advance_parser.add_argument(
        "--progress",
        required=True,
        help="Путь к progress-файлу (JSON)",
    )
    advance_parser.add_argument(
        "--step",
        help=(
            "Явное указание завершаемого шага; должен совпадать с current_step_id "
            "(защита от случайного пропуска)"
        ),
    )
    advance_parser.add_argument(
        "--note",
        help="Заметка к завершённому шагу (что сделано, какие решения приняты)",
    )
    advance_parser.add_argument(
        "--repository",
        help="Обновить current_position.current_repository после перехода",
    )
    advance_parser.add_argument(
        "--resume-hint",
        help="Подсказка для возобновления работы (куда смотреть в следующий раз)",
    )
    advance_parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Продолжить даже при наличии ошибок валидации progress-файла",
    )
    advance_parser.set_defaults(func=advance_command)

    # ------------------------------------------------------------------
    # domain — управление доменной картой репозитория
    # ------------------------------------------------------------------
    domain_parser = subparsers.add_parser(
        "domain",
        help=(
            "Доменная карта репозитория: оценить объём, зарегистрировать домены/поддомены, "
            "начать и завершить анализ домена"
        ),
    )
    domain_parser.add_argument(
        "--progress",
        required=True,
        help="Путь к progress-файлу (JSON)",
    )
    domain_parser.add_argument(
        "--repo",
        required=True,
        help="Имя репозитория, к которому применяется действие над доменом",
    )
    domain_parser.add_argument(
        "--domain-id",
        help="Уникальный идентификатор домена внутри репозитория (snake_case)",
    )
    domain_parser.add_argument(
        "--name",
        help="Человекочитаемое название домена",
    )
    domain_parser.add_argument(
        "--description",
        default="",
        help="Краткое описание домена",
    )
    domain_parser.add_argument(
        "--paths",
        help="Пути внутри репозитория, принадлежащие домену (через запятую)",
    )
    domain_parser.add_argument(
        "--signal",
        help="Структурный сигнал, по которому домен был выделен (например: 'apps/payments/')",
    )
    domain_parser.add_argument(
        "--subdomain-id",
        help="Уникальный идентификатор поддомена",
    )
    domain_parser.add_argument(
        "--subdomain-name",
        help="Человекочитаемое название поддомена",
    )
    domain_parser.add_argument(
        "--notes",
        help="Заметка к операции над доменом",
    )
    # действия (ровно одно из пяти)
    domain_parser.add_argument(
        "--assess",
        action="store_true",
        help="Записать результат оценки объёма репозитория (strategy, volume-class, total-files)",
    )
    domain_parser.add_argument(
        "--register",
        action="store_true",
        help="Зарегистрировать новый домен в domain_map репозитория",
    )
    domain_parser.add_argument(
        "--add-subdomain",
        action="store_true",
        help="Добавить поддомен в существующий домен",
    )
    domain_parser.add_argument(
        "--start",
        action="store_true",
        help="Начать анализ домена (соблюдает порядок из ordered_domain_ids)",
    )
    domain_parser.add_argument(
        "--complete",
        action="store_true",
        help="Завершить анализ текущего домена",
    )
    domain_parser.add_argument(
        "--strategy",
        choices=["per_module", "per_domain"],
        default="per_module",
        help=(
            "Стратегия обхода репозитория: "
            "per_module — единый проход, per_domain — домен за доменом "
            "(по умолчанию: per_module)"
        ),
    )
    domain_parser.add_argument(
        "--volume-class",
        choices=["small", "medium", "large", "xlarge"],
        help="Класс объёма репозитория по числу файлов",
    )
    domain_parser.add_argument(
        "--total-files",
        type=int,
        help="Оценочное количество файлов в репозитории",
    )
    domain_parser.set_defaults(func=domain_command)

    # ------------------------------------------------------------------
    # validate-contracts — проверить OpenAPI/AsyncAPI файлы контрактов
    # ------------------------------------------------------------------
    contracts_parser = subparsers.add_parser(
        "validate-contracts",
        help=(
            "Проверить OpenAPI (*-sync.yml) и AsyncAPI (*-async.yml) файлы контрактов "
            "в указанной директории"
        ),
    )
    contracts_parser.add_argument(
        "--contracts-dir",
        required=True,
        help=(
            "Путь к директории с файлами контрактов "
            "(ожидаются *-sync.yml и/или *-async.yml)"
        ),
    )
    contracts_parser.set_defaults(func=validate_contracts_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)
