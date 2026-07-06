# Точечный глубокий разбор по категориям сигналов

Используй этот reference на шаге `targeted_deep_analysis`. К этому моменту у репозитория уже есть список сработавших категорий (`signal_categories`) из `signal_mapping`.

## Принцип ограниченного чтения

Не открывай весь репозиторий. Для каждой категории:

1. Возьми список путей, зафиксированных за этой категорией (`source_paths`).
2. Прочитай сами изменившиеся файлы целиком (не только diff-фрагмент — diff без контекста окружающего кода часто вводит в заблуждение).
3. Прочитай файлы, которые **вызывают** или **вызываются** изменившимся кодом, если это нужно для понимания эффекта (например, если изменился DTO — проверь обработчик, который его использует; если изменилась миграция — проверь модель/ORM).
4. Не расширяй чтение на модули, не связанные с дельтой, даже если они относятся к той же категории в других частях репозитория.

## Маппинг категория → reference

Глубина и критерии разбора по каждой категории такие же, как при первичном анализе:

| Категория сигнала | Reference |
|---|---|
| `repository_classification` | [checklist-repository-classification.md](checklist-repository-classification.md) |
| `repository_structure_mapping` | [checklist-repository-structure-mapping.md](checklist-repository-structure-mapping.md) |
| `entrypoints_and_interfaces`, `ui_screens_and_navigation` | [checklist-entrypoints-and-interfaces.md](checklist-entrypoints-and-interfaces.md) |
| `business_flow_orchestration` | [checklist-business-flow-orchestration.md](checklist-business-flow-orchestration.md) |
| `configs_and_runtime` | [checklist-configs-and-runtime.md](checklist-configs-and-runtime.md) |
| `tech_stack_collection` | [checklist-tech-stack.md](checklist-tech-stack.md) |
| `contracts_and_schemas` | [checklist-contracts-and-schemas.md](checklist-contracts-and-schemas.md) |
| `data_and_storage` | [checklist-data-and-storage.md](checklist-data-and-storage.md) |
| `domain_entities` | [checklist-domain-entities.md](checklist-domain-entities.md) |
| `integrations_and_dependencies` | [checklist-integrations-and-dependencies.md](checklist-integrations-and-dependencies.md) |
| `tests_and_behavior_evidence` | [checklist-tests-and-behavior-evidence.md](checklist-tests-and-behavior-evidence.md) |
| `glossary_updates`, `open_questions_review_and_updates` | [checklist-glossary-and-open-questions.md](checklist-glossary-and-open-questions.md) |
| `feature_discovery_and_updates`, `features_index_updates` | [checklist-features-and-index.md](checklist-features-and-index.md) |
| `roles_and_permissions_updates`, `security_and_auth_updates`, `deployment_and_operability`, `risks_and_tech_debt_updates` | [checklist-roles-security-operability-risks.md](checklist-roles-security-operability-risks.md) |

## Отличие применения чеклиста при обновлении

При первичном анализе чеклист применяется к **всему репозиторию**. При обновлении — только к зоне, затронутой дельтой:

- Сверяй новое/изменённое поведение с уже существующим артефактом (`architecture/contracts/<service>-*.yml`, `architecture/storage/<service>.yml`, `architecture/integrations/<service>.md` и т.д.), а не пересоздавай его с нуля.
- Если дельта **добавляет** новый факт — допиши его в существующий артефакт.
- Если дельта **меняет** существующий факт — обнови соответствующий блок и явно отметь, что предыдущее описание устарело (не оставляй два противоречащих друг другу утверждения в одном файле).
- Если дельта **удаляет** поведение (endpoint, поле, интеграция) — удали соответствующий блок из артефакта; не оставляй описание мёртвого кода как актуального.

## Завершение категории

После обновления артефактов отметь категорию завершённой:

```
update_guard.py signal --repo <repo> --category <id> --status completed --notes "<что обновлено и в каких файлах>"
```

Нельзя завершить `targeted_deep_analysis` для репозитория, пока хотя бы одна зарегистрированная категория не в статусе `completed` или `blocked` с явной причиной в `notes`.
