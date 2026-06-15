from __future__ import annotations

STEP_DEFINITIONS = [
    (
        "define_scope",
        "Определить продукт, контур и границы анализа",
    ),
    (
        "request_repository_list",
        "Запросить у пользователя полный список репозиториев",
    ),
    (
        "prepare_temp_workspace",
        "Подготовить .temp и добавить его в .gitignore",
    ),
    (
        "clone_repositories",
        "Клонировать в .temp все репозитории из пользовательского списка",
    ),
    (
        "refresh_main_branches",
        "Для каждого репозитория зафиксировать main branch и commit SHA",
    ),
    (
        "plan_repository_order",
        "Определить порядок обхода репозиториев",
    ),
    (
        "analyze_repositories",
        "Проанализировать репозитории и собрать технические факты",
    ),
    (
        "interview_user",
        "Задать пользователю только вопросы по пробелам после анализа кода",
    ),
    (
        "validate_final",
        "Провести финальную валидацию артефактов",
    ),
    (
        "finalize_progress",
        "Зафиксировать итоговый статус анализа, пробелы и следующий шаг",
    ),
]

STEP_INDEX = {step_id: idx for idx, (step_id, _) in enumerate(STEP_DEFINITIONS)}

REPOSITORY_CHECKLIST_DEFINITIONS = [
    (
        "scope_and_domain_assessment",
        "Оценить объём репозитория и выявить бизнес-домены и поддомены; определить стратегию per_repository или per_domain",
    ),
    ("repository_characterization", "Определить тип и роль репозитория в системе"),
    (
        "test_repository_classification",
        "Определить, является ли репозиторий отдельным e2e или integration test-репозиторием; если да — зафиксировать, какие сервисы покрывает",
    ),
    ("entrypoints_and_interfaces", "Найти точки входа и внешние интерфейсы"),
    ("business_flow_orchestration", "Разобрать orchestration и бизнес-потоки"),
    ("configs_and_runtime", "Собрать конфиги и runtime-зависимости"),
    (
        "tech_stack_collection",
        "Собрать технологический стек → зафиксировать ЯП, runtime, framework, ORM, transport, broker clients, observability, security и архитектурно значимые SDK в architecture/tech-stack.md",
    ),
    (
        "contracts_and_schemas",
        "Собрать контракты, DTO и схемы → создать contracts/<service>-sync.yml (HTTP/REST/gRPC) и contracts/<service>-async.yml (Kafka/AMQP/gRPC-stream); если нет — явно написать 'нет' в notes",
    ),
    (
        "data_and_storage",
        "Разобрать storage, модели, миграции, topics и cache → создать architecture/storage/<service>.yml",
    ),
    (
        "domain_entities",
        "Выделить ключевые бизнес-сущности, видимые пользователю/внешней системе: собрать поля с фронтенда и бэкенда, пометить backend_only поля → обновить architecture/domain-entities.md",
    ),
    (
        "integrations_and_dependencies",
        "Собрать интеграции и зависимости → создать architecture/integrations/<service>.md",
    ),
    ("tests_and_behavior_evidence", "Собрать сильные подтверждения из integration/e2e/tests"),
    ("glossary_updates", "Обновить glossary по новым и неоднозначным терминам"),
    (
        "open_questions_review_and_updates",
        "Пересмотреть открытые вопросы и закрыть те, что подтверждаются новым репозиторием",
    ),
    ("feature_discovery_and_updates", "Выделить и обновить текущие features по новой информации"),
    ("features_index_updates", "Обновить корневой реестр фич"),
    ("roles_and_permissions_updates", "Обновить роли и матрицу функционала"),
    (
        "security_and_auth_updates",
        "Зафиксировать модель аутентификации и границы доверия → обновить architecture/security.md: механизмы аутентификации пользователей и сервисов, межсервисное доверие, чувствительные данные и шифрование; если данных нет — явно написать 'не удалось восстановить' в notes",
    ),
    ("deployment_and_operability", "Проверить deploy, observability и operability сигналы"),
    (
        "risks_and_tech_debt_updates",
        "Зафиксировать известные риски и технический долг → обновить architecture/risks.md: хрупкие места, EOL-зависимости, отсутствующие retry/circuit breakers, незащищённые эндпоинты, известные инциденты; если рисков не выявлено — явно написать 'рисков не выявлено' в notes",
    ),
    (
        "architecture_artifact_updates",
        "Обновить landscape, tech-stack, features; проверить наличие storage/<svc>.yml, integrations/<svc>.md, contracts/<svc>-sync.yml, contracts/<svc>-async.yml, обновлённого architecture/security.md и architecture/risks.md (или явную пометку в notes)",
    ),
    (
        "repository_consistency_review",
        "Финальная проверка согласованности артефактов репозитория перед закрытием: entrypoints ↔ contracts, contracts ↔ integrations, storage ↔ HLD, features ↔ entrypoints, domain-entities ↔ contracts+storage; исправить расхождения, зафиксировать итог в notes",
    ),
]

CHECKLIST_INDEX = {item_id: idx for idx, (item_id, _) in enumerate(REPOSITORY_CHECKLIST_DEFINITIONS)}
