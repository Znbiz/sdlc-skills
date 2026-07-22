# Обязательная чистка документации от удалённой функциональности при анализе репозитория

**Цель:** сейчас `route_checklist_items`/чек-лист шага 8 (`analyze_repositories_item`) устроены так, что
`deleted_paths` репозитория трактуются наравне с `changed_paths`/`renamed_paths` — как сигнал для роутинга
категорий, но не как повод что-то **убрать** из уже написанной документации. Ни один reference-файл
чек-листа не содержит инструкции «если код, который описывала фича/эндпоинт/таблица/роль, удалён —
почисти документацию». Из-за этого `features/*.md`, `architecture/*.md`, `features-index.md` и т.д. могут
годами хранить описания давно удалённого функционала, и это никак не проверяется — ни детерминированным
lint'ом, ни промптом. Нужно: (1) добавить новый, обязательный и **первый по порядку** пункт чек-листа для
каждого репозитория, который явно ищет и чистит документацию по всем `Удалённые пути` текущего diff; (2)
добавить в каждый существующий пункт чек-листа короткую инструкцию перепроверять актуальность **в своей
предметной области** и удалять из документации то, что относится к удалённому коду — как защита на случай,
если первый широкий проход что-то пропустил.

**Статус:** done. Все фазы 1-5 реализованы.

## Проблема

`RepositoryExecution.deleted_paths` собирается вместе с `changed_paths`/`renamed_paths` в `_touched_paths()`
([signal_routing.py:65-66](../../back/app/workflows/init_arch/domain/signal_routing.py#L65-L66)) и участвует
в `classify_diff_severity`/`route_checklist_items` ровно как любой другой путь — сигнализирует «этот
репозиторий что-то менял», но не «в документации может быть мусор про удалённое». Ни один из 16
reference-файлов под `CHECKLIST_ITEM_TO_REFERENCE`
([prompts.py:55-77](../../back/app/workflows/init_arch/prompts.py#L55-L77)) не содержит инструкции про
удаление устаревших описаний. Промпт для `analyze_repositories` уже показывает агенту полный (не урезанный)
список `Удалённые пути` — `_build_temporal_delta_block(..., expanded=True)`, т.к. `analyze_repositories` в
`_EXPANDED_DIFF_CONTEXT_STEPS` ([prompts.py:15](../../back/app/workflows/init_arch/prompts.py#L15),
[prompts.py:152](../../back/app/workflows/init_arch/prompts.py#L152)) — то есть техническая возможность
увидеть, что именно удалено, уже есть, просто нет ни одной инструкции ей воспользоваться для чистки
документации, и нет проверки на это ни в `run_knowledge_lint`, ни в `validate_final`.

## Принятые решения по архитектуре

- **Новый пункт чек-листа `deleted_functionality_cleanup`**, свой reference-файл
  `checklist-deleted-functionality-cleanup.md`. Не переиспользуем существующие пункты — чистка удалённого
  логически ортогональна и «сбору находок» (остальные пункты), и «финальной сверке» (`repository_consistency_review`,
  которая сверяет артефакты друг с другом, а не с фактом удаления кода).
- **Ставим его первым в порядке выполнения для каждого репозитория.** Порядок `analyze_repositories_item`
  определяется порядком ключей в `CHECKLIST_ITEM_TO_REFERENCE` (см. `next_pending_checklist_item` →
  `route_checklist_items(..., all_checklist_item_ids=list(CHECKLIST_ITEM_TO_REFERENCE))` — фильтрация
  сохраняет порядок входного списка, [signal_routing.py:114](../../back/app/workflows/init_arch/domain/signal_routing.py#L114)).
  Новый ключ становится **первой** записью словаря — раньше `repository_classification`. Мотивация: остальные
  пункты (структура, entrypoints, фичи и т.д.) должны анализировать репозиторий на уже почищенной от мусора
  документации, а не рисковать тем, что стоящее рядом устаревшее описание собьёт агента с толку или он примет
  его за всё ещё актуальное.
- **Обязателен для любого непустого diff**, не diff-routed. Добавляется в `_ALWAYS_ROUTED_CHECKLIST_ITEMS`
  ([signal_routing.py:10-16](../../back/app/workflows/init_arch/domain/signal_routing.py#L10-L16)) — по той
  же логике, что уже применена к `feature_discovery_and_updates`/`features_index_updates` в
  [2026-07-22-mandatory-per-repo-feature-sync-and-final-feature-review.md](2026-07-22-mandatory-per-repo-feature-sync-and-final-feature-review.md):
  `NO_SIGNAL` (пустой diff за окно) не меняется — если ничего не менялось, удалять нечего.
- **Явно опираться на разделение `deleted_paths`/`renamed_paths`, уже сделанное в domain-модели.**
  `RepositoryExecution` хранит их раздельно — переименованный файл не должен трактоваться как удаление
  (иначе агент по ошибке удалит документацию про функциональность, которая просто переехала). Reference-файл
  явно инструктирует сверяться с обоими списками, а не только с `deleted_paths`.
- **Не удалять вслепую.** Если сопоставление «эта фича/эндпоинт/таблица описывает именно этот удалённый
  путь» неочевидно (общий helper, переиспользуемый модуль, частичное удаление одного из нескольких файлов
  одной capability) — не удалять запись целиком, а: (а) для полностью пропавшей capability — удалить/пометить
  раздел; (б) для частичного удаления — обновить трассировку, оставив то, что ещё существует; (в) если
  неочевидно — открыть `open_questions`, а не гадать. Симметрично Правилу статуса из
  `checklist-features-and-index.md` (`implemented`/`partial`/`unknown`).
- **Второй, defense-in-depth слой: короткая инструкция в каждом из 15 остальных reference-файлов** («на своём
  уровне: если код, лежащий в основе описанного тобой артефакта, удалён по `Удалённые пути` — удали/обнови
  соответствующую запись»), сформулированная в терминах конкретно того артефакта, за который отвечает данный
  пункт (endpoint/схема — для `contracts_and_schemas`, таблица/миграция — для `data_and_storage`, роль/право —
  для `roles_and_permissions_updates` и т.д.), а не общей фразой. Это не дублирование первого пункта, а
  подстраховка: первый пункт видит весь diff разом и может что-то упустить в конкретной узкой предметной
  области, которую специализированный пункт разбирает подробнее.
- **`checklist-repository-classification.md` содержит таблицу применимости пунктов чек-листа для
  support-репозиториев** ([checklist-repository-classification.md:54-76](../../back/app/workflows/shared_assets/init_arch/references/checklist-repository-classification.md#L54-L76)) —
  новый пункт `deleted_functionality_cleanup` должен получить свою строку в этой таблице (применим для всех
  трёх типов `library`/`test-repo`/`infra` — у support-репозиториев тоже есть своя документация в
  `support-repositories.md`/`architecture/tech-stack.md`/т.д., которая может устареть при удалении кода).
- **Без изменений в `nodes.py`/топологии графа.** Как и в предыдущей спеке — это вопрос
  routing-конфигурации и содержания промптов, не физических узлов. `collect_worker_artifacts` по-прежнему не
  вызывается в `analyze_repositories_item` (см. ноду 8 в [init-graph-reference.md](../workflows/init-graph-reference.md)) —
  правки/удаления файлов, которые агент сделает в рамках этого пункта, физически появятся на диске, но не
  зарегистрируются в `session.artifacts`/`ARTIFACT_WRITTEN`, ровно как и для остальных пунктов этого шага.

## Фазы

### Фаза 1 — новый checklist item в роутинге `[x]`

- `prompts.py`: добавить `"deleted_functionality_cleanup": "references/checklist-deleted-functionality-cleanup.md"`
  **первой** записью в `CHECKLIST_ITEM_TO_REFERENCE`.
- `signal_routing.py`: добавить `"deleted_functionality_cleanup"` в `_ALWAYS_ROUTED_CHECKLIST_ITEMS`.
- Тесты в `test_signal_routing.py`: обновить `_ALL_ITEMS` (добавить пункт первым), обновить
  `test_local_with_unmatched_paths_routes_only_always_routed` (теперь 5 always-routed пунктов вместо 4, в
  правильном порядке), `test_no_signal_does_not_route_feature_items`/аналогичный явный тест на то, что
  `NO_SIGNAL` не роутит и новый пункт тоже.
- Тесты в `test_nodes.py`, использующие `next(iter(CHECKLIST_ITEM_TO_REFERENCE))` — уже написаны обобщённо
  (не хардкодят `"repository_classification"|"..."`), должны остаться зелёными без изменений; проверить по
  факту после правки.

**Мини-отчёт**: реализовано без отклонений от плана. `CHECKLIST_ITEM_TO_REFERENCE`
([prompts.py:55-56](../../back/app/workflows/init_arch/prompts.py#L55-L56)) получил
`"deleted_functionality_cleanup": "references/checklist-deleted-functionality-cleanup.md"` первой записью,
перед `repository_classification`. `_ALWAYS_ROUTED_CHECKLIST_ITEMS` в `signal_routing.py` расширен с 4 до 5
элементов. В `test_signal_routing.py`: `_ALL_ITEMS` дополнен новым пунктом первой позицией;
`test_local_routes_impacted_categories_plus_always_routed` дополнен assert'ом на присутствие нового пункта;
`test_local_with_unmatched_paths_routes_only_always_routed` обновлён на 5 элементов с новым пунктом первым;
`test_no_signal_does_not_route_feature_items` дополнен проверкой, что новый пункт тоже не роутится при
`NO_SIGNAL`; добавлен новый тест `test_local_routes_deleted_functionality_cleanup_first`, который явно
фиксирует требование «первым в порядке выполнения» (a не просто «где-то в списке») — с одновременно и
`changed_paths`, и `deleted_paths` в диффе, чтобы исключить случай, когда пункт первый просто потому, что
больше нечему было попасть в routed-список. `test_nodes.py`/`test_prompts.py`, использующие
`next(iter(CHECKLIST_ITEM_TO_REFERENCE))` обобщённо, не потребовали правок — подтверждено прогоном.
`pytest tests/workflows/init_arch`: 266 passed, 1 xfailed (было 265+1 до фазы), 0 регрессий.
`ruff check`/`ruff format --check` на `prompts.py`, `signal_routing.py`, `test_signal_routing.py` чисты.

### Фаза 2 — новый reference-файл `checklist-deleted-functionality-cleanup.md` `[x]`

Содержание: прочитать `Удалённые пути` (и отдельно `Переименованные пути` — как контрпример, не путать) из
temporal delta блока текущего repo; для каждого удалённого пути — найти упоминания в
`features/*.md`/`architecture/*.md`/`architecture/contracts/*`/`architecture/storage/*`/`wiki/*` (grep по пути
и по basename); определить: capability полностью пропала (все точки входа/трассировка мертвы) → удалить или
пометить как `removed`/deprecated + убрать строку из `features-index.md`; capability частично пропала →
обновить трассировку, понизить статус реализации по Правилу статуса, если пропал единственный тест/entrypoint;
неочевидно → `open_questions`, не гадать. Явно предупредить не путать удаление с переименованием (сверяться с
`renamed_paths`).

**Мини-отчёт**: файл создан по плану, без отклонений —
[checklist-deleted-functionality-cleanup.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-deleted-functionality-cleanup.md).
Структура повторяет стиль остальных reference-файлов (заголовок с именем пункта, «Шаги выполнения»,
«Обязательные выходы», «Подводные камни»). Ключевые решения из спеки перенесены буквально: явное разделение
`deleted_paths`/`renamed_paths` (шаг 2), три исхода на каждое найденное упоминание — «полностью исчезла» /
«частично изменилась» / «неочевидно → open_questions», а не бинарное «удалить или нет» (шаг 4), обязательный
содержательный вывод в `notes` даже когда удалённых путей не было (шаг 5, симметрично тому же требованию в
`checklist-features-and-index.md` для отсутствия новых фич). В «Подводные камни» добавлено явное указание,
что это не единственный рубеж защиты — остальные пункты чек-листа тоже перепроверяют в своей области (см.
Фазу 4), чтобы у агента не создавалось ложное ощущение «раз я не нашёл — значит, нечего искать и остальным
пунктам».

### Фаза 3 — строка в таблице применимости support-репозиториев `[x]`

В `checklist-repository-classification.md` добавить строку `deleted_functionality_cleanup` в таблицу
применимости (раздел «Если категория support») — применимо для всех трёх типов.

**Мини-отчёт**: строка `deleted_functionality_cleanup` добавлена первой в таблицу применимости
([checklist-repository-classification.md:58](../../back/app/workflows/shared_assets/init_arch/references/checklist-repository-classification.md#L58)) —
применимо для всех трёх типов (`library`/`test-repo`/`infra`), с уточнением, что у support-репозиториев своя
документация (`support-repositories.md`, `tech-stack.md`) устаревает точно так же. Заодно (этот файл сам —
один из 15, требующих defense-in-depth инструкции по Фазе 4) в раздел «Проверка согласованности и правка
артефактов» добавлен пункт про пересмотр категории/роли при удалении: если `product`-репозиторий лишился
единственной продуктовой capability — пересмотреть категорию на `support`; если `support`-репозиторий лишился
той функциональности, ради которой был support (например, `test-repo` без тестов) — зафиксировать в
`open-questions.md`, не удаляя запись молча. Это закрывает и Фазу 3, и часть Фазы 4 для этого конкретного
файла одним заходом, т.к. они географически рядом.

### Фаза 4 — defense-in-depth инструкция в остальных 15 reference-файлах `[x]`

По одному короткому, специфичному для артефакта абзацу/пункту в каждом из: `checklist-repository-structure-mapping.md`,
`checklist-entrypoints-and-interfaces.md`, `checklist-business-flow-orchestration.md`, `checklist-configs-and-runtime.md`,
`checklist-tech-stack.md`, `checklist-contracts-and-schemas.md`, `checklist-data-and-storage.md`,
`checklist-domain-entities.md`, `checklist-integrations-and-dependencies.md`, `checklist-tests-and-behavior-evidence.md`,
`checklist-glossary-and-open-questions.md`, `checklist-features-and-index.md`,
`checklist-roles-security-operability-risks.md`, `checklist-architecture-artifact-updates.md`,
`checklist-repository-consistency-review.md`.

**Мини-отчёт**: `checklist-repository-classification.md` уже получил свою инструкцию в рамках Фазы 3 (одним
заходом, т.к. правки географически совпали). Остальные 14 файлов дополнены по одному bullet'у, каждый
сформулирован в терминах конкретного артефакта этого пункта, а не общей фразой:
`checklist-repository-structure-mapping.md` (запись категории в `architecture/structure/<repo>.yml`),
`checklist-entrypoints-and-interfaces.md` (точка входа в `hld.md`/трассировке фичи),
`checklist-business-flow-orchestration.md` (поток в разделе «Основные потоки» `hld.md`),
`checklist-configs-and-runtime.md` (env var/feature flag),
`checklist-tech-stack.md` (зависимость/технология в `tech-stack.md`),
`checklist-contracts-and-schemas.md` (endpoint/схема в `architecture/contracts/*`),
`checklist-data-and-storage.md` (таблица в `architecture/storage/*.yml` — с явным уточнением не путать
удаление ORM-модели с реальным DROP-миграцией, см. «Принятые решения»),
`checklist-domain-entities.md` (сущность в `domain-entities.md`),
`checklist-integrations-and-dependencies.md` (интеграция в `integrations-overview.md`),
`checklist-tests-and-behavior-evidence.md` (тест, подтверждавший статус `implemented` — понижение статуса,
а не молчаливое сохранение),
`checklist-glossary-and-open-questions.md` (термин в `glossary.md` + закрытие открытых вопросов про удалённую
функциональность),
`checklist-features-and-index.md` (фича целиком/частично — с явной отсылкой к Правилу статуса, чтобы не
дублировать логику из уже существующей «Часть 3»),
`checklist-roles-security-operability-risks.md` (один bullet на все 4 артефакта: roles/security/risks/deploy),
`checklist-architecture-artifact-updates.md` (сформулирован как финальный по всем `architecture/*.md` проход
— «то, что осталось» после более специализированных пунктов, а не дублирование),
`checklist-repository-consistency-review.md` (новый checkbox-блок «Удалённые пути ↔ Документация» в общем
списке проверок согласованности, как последний рубеж перед `repo --complete`).
Все правки вставлены в уже существующие секции («Проверка согласованности и правка артефактов»/«Подводные
камни»/аналог), без создания новых заголовков, кроме `checklist-repository-consistency-review.md`, где по
формату файла нужен был отдельный `**X ↔ Y**` блок — стиль, уже используемый для всех остальных пар в этом
файле. `markdownlint-cli2` на этом файле показывает 26 warning'ов (MD013/MD032/MD036) — подтверждено, что все
эти правила нарушались уже во всех pre-existing блоках файла до моей правки (24 из 26), новый блок добавил
ровно 2 таких же warning'а того же типа, что и остальные — не новый регресс, а согласованность с
существующим (нестрогим) стилем файла.

### Фаза 5 — документация графа `[x]`

`init-graph-reference.md`, нода 8: таблица reference-файлов + текст про порядок выполнения и
`_ALWAYS_ROUTED_CHECKLIST_ITEMS`, со ссылкой на эту спеку.

**Мини-отчёт**: в ноду 8 добавлен абзац «Первый пункт — чистка удалённой функциональности» сразу после уже
существующего абзаца про обязательность feature-пунктов (из предыдущей спеки) — описывает, что новый пункт
одновременно и `_ALWAYS_ROUTED_CHECKLIST_ITEMS`, и первый по порядку ключей в `CHECKLIST_ITEM_TO_REFERENCE`,
поэтому гарантированно исполняется первым для любого репозитория с непустым диффом; также упомянута
defense-in-depth инструкция в остальных 15 пунктах, со ссылкой на эту спеку. Таблица reference-файлов
дополнена первой строкой `deleted_functionality_cleanup` → `checklist-deleted-functionality-cleanup.md`.

## Тестирование

`pytest tests/workflows/init_arch` — 0 регрессий; `ruff check`/`ruff format --check` на изменённых `.py`.
Markdown-контент без unit-тестов, кроме как через существующий сьют (`_load_shared_asset` не парсит
структуру файлов).

**Итоговая проверка (после всех фаз)**: `pytest tests/workflows/init_arch` — 266 passed, 1 xfailed, 0
регрессий; `ruff check`/`ruff format --check` на `prompts.py`/`signal_routing.py`/`test_signal_routing.py` —
чисто.

## Критерии готовности

- `deleted_functionality_cleanup` — первый пункт чек-листа, обязателен для любого непустого diff.
- Reference-файл явно различает `deleted_paths`/`renamed_paths` и не удаляет вслепую при неочевидном случае.
- Все 15 остальных reference-файлов имеют собственную, специфичную для артефакта инструкцию по чистке.
- `init-graph-reference.md` (нода 8) отражает изменение со ссылкой на эту спеку.
- 0 регрессий в существующем сьюте.

## Out of scope

- Детерминированный lint, сверяющий трассировку с фактическим состоянием репозитория (например, «путь X всё
  ещё существует в HEAD») — обсуждалось как gap ранее, но это отдельная, более крупная задача (нужен доступ к
  raw checkout на этапе lint, которого сейчас у `run_knowledge_lint` нет). Здесь всё ещё LLM-driven чистка, не
  автоматическая проверка.
- Изменение топологии графа / `nodes.py` / регистрация `collect_worker_artifacts` для этого шага — не входит,
  см. «Принятые решения».
