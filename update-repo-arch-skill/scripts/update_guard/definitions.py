from __future__ import annotations

STEP_DEFINITIONS = [
    (
        "load_baseline",
        "Восстановить предыдущий baseline по каждому репозиторию",
    ),
    (
        "refresh_repositories",
        "Обновить репозитории до актуального коммита основной ветки",
    ),
    (
        "triage_repositories",
        "Классифицировать дельту по каждому репозиторию (none/minor/significant)",
    ),
    (
        "signal_mapping",
        "Сопоставить изменившиеся пути с категориями артефактов",
    ),
    (
        "targeted_deep_analysis",
        "Точечно обновить артефакты по сработавшим категориям",
    ),
    (
        "cascade_check",
        "Проверить каскадные эффекты на другие репозитории и артефакты",
    ),
    (
        "consistency_validation",
        "Провести финальную проверку согласованности затронутых артефактов",
    ),
    (
        "finalize_update",
        "Зафиксировать новый baseline и отчёт о прогоне",
    ),
]

STEP_INDEX = {step_id: idx for idx, (step_id, _) in enumerate(STEP_DEFINITIONS)}

# Категории сигналов 1:1 с частью analysis_checklist первичного анализа.
# Не фиксированный чеклист на репозиторий — регистрируются динамически только
# те категории, на которые указала дельта (см. checklist-signal-routing.md).
SIGNAL_CATEGORY_DEFINITIONS = [
    (
        "repository_classification",
        "Изменилась роль/тип репозитория или появился новый верхнеуровневый модуль",
    ),
    (
        "repository_structure_mapping",
        "Структура каталогов разошлась с architecture/structure/<repo>.yml: появились/переименовались/удалились пути, не покрытые картой — карту нужно актуализировать",
    ),
    ("entrypoints_and_interfaces", "Изменились точки входа и внешние интерфейсы"),
    ("ui_screens_and_navigation", "Изменились экраны/страницы/роуты или навигация между ними (frontend)"),
    ("business_flow_orchestration", "Изменился orchestration или бизнес-поток"),
    ("configs_and_runtime", "Изменились конфиги или runtime-зависимости"),
    ("tech_stack_collection", "Изменился технологический стек или ключевые зависимости"),
    ("contracts_and_schemas", "Изменились контракты, DTO или схемы"),
    ("data_and_storage", "Изменились storage, модели, миграции, topics или cache"),
    ("domain_entities", "Изменились ключевые бизнес-сущности, видимые пользователю/внешней системе"),
    ("integrations_and_dependencies", "Изменились интеграции и зависимости"),
    ("tests_and_behavior_evidence", "Изменились integration/e2e/тесты со значимыми сигналами"),
    ("glossary_updates", "Появились новые или изменились существующие термины"),
    ("open_questions_review_and_updates", "Дельта закрывает или открывает вопросы"),
    ("feature_discovery_and_updates", "Изменились или появились capability/сценарии"),
    ("features_index_updates", "Нужно обновить корневой реестр фич"),
    ("roles_and_permissions_updates", "Изменились роли или матрица функционала"),
    ("security_and_auth_updates", "Изменилась модель аутентификации или границы доверия"),
    ("deployment_and_operability", "Изменились deploy, observability или operability сигналы"),
    ("risks_and_tech_debt_updates", "Появились новые риски или технический долг"),
]

SIGNAL_CATEGORY_INDEX = {
    category_id: idx for idx, (category_id, _) in enumerate(SIGNAL_CATEGORY_DEFINITIONS)
}

DIFF_CLASSIFICATIONS = ("none", "minor", "significant")
REPO_STATUSES = (
    "not_started",
    "in_progress",
    "completed",
    "skipped_no_changes",
    "blocked",
)
ITEM_STATUSES = ("not_started", "in_progress", "completed", "blocked")
