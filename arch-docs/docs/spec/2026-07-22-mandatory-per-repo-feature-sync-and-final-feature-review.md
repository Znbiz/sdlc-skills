# Гарантировать per-repo синхронизацию фич в конце шага 8 и финальную сверку всех фич в шаге 10

**Цель:** сейчас пункты чек-листа `feature_discovery_and_updates`/`features_index_updates` (нода 8,
`analyze_repositories_item`) — обычные diff-routed пункты: при `local`/`no_signal` diff severity они
пропускаются, если задетые пути репозитория не попали ни в одну категорию `_PATH_SIGNAL_CATEGORIES`
(а фичи там не участвуют вообще ни в одной категории — см. «Проблема»). Из-за этого выделение/актуализация
фич может не выполняться для части репозиториев в мульти-репозиторном прогоне, хотя каждый репозиторий может
нести свой кусок продуктовой capability. А нода 10 (`refine_features`) сейчас делает один LLM-вызов
«допиши/уточни фичи» без явного требования пройтись по **всем уже существующим** файлам `features/*.md` и
`features-index.md` целиком и проверить их на полноту, непротиворечивость и отсутствие пропусков. Нужно:
(1) сделать выделение/обновление фич обязательным по итогам анализа каждого репозитория в шаге 8, а не
diff-routed; (2) сделать шаг 10 явной финальной сверкой по всему реестру фич с правкой при необходимости.

**Статус:** done. Все фазы 1-4 реализованы.

## Проблема

### 1. Feature-пункты чек-листа в шаге 8 не гарантированы

`route_checklist_items()` ([signal_routing.py:99-114](../../back/app/workflows/init_arch/domain/signal_routing.py#L99-L114))
возвращает урезанный набор пунктов для `DiffSeverity.LOCAL`/`NO_SIGNAL`:

```python
_ALWAYS_ROUTED_CHECKLIST_ITEMS: typing.Final[frozenset[str]] = frozenset(
    {"architecture_artifact_updates", "repository_consistency_review"}
)
```

`feature_discovery_and_updates`/`features_index_updates` в этот frozenset не входят и ни разу не встречаются
как категория ни в одной записи `_PATH_SIGNAL_CATEGORIES`
([signal_routing.py:14-55](../../back/app/workflows/init_arch/domain/signal_routing.py#L14-L55)) — то есть
для `LOCAL`-диффа (задетые top-level директории ≤ 3, самый частый случай в инкрементальном прогоне по
множеству репозиториев) эти два пункта **не могут** попасть в `routed_categories` ни при каком наборе
задетых путей: они появляются только при `FULL_REQUIRED`/`BROAD` severity, когда возвращается весь чек-лист
целиком. Так задокументировано и в
[checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md) —
шаги выполнения там подразумевают полный прогон, а не «пропустить, если diff локальный».

Следствие: если репозиторий за прошедшее temporal-окно получил узкий, но продуктово значимый diff (например,
только `services/checkout/` — 1 top-level dir, `LOCAL`), пункты выделения фич не попадут в routed-набор
(`services/` маппится на `business_flow_orchestration`, не на фичи) — новая или изменившаяся capability из
этого репозитория не будет отражена в `features/*.md`/`features-index.md`, пока в другом temporal-окне не
случится `FULL_REQUIRED`/`BROAD` diff. Это расходится с намерением: реестр фич должен пополняться по каждому
проанализированному репозиторию, а не только по репозиториям с широким диффом.

### 2. `refine_features` не формулирует явную финальную сверку по всем фичам

`node_refine_features` ([nodes.py:773-816](../../back/app/workflows/init_arch/nodes.py#L773-L816)):
`bootstrap_arch_repo` (детерминированно, скелет каталогов/шаблонов) → один LLM-вызов
(`task_kind` по умолчанию, reference `checklist-features-and-index.md`) → `collect_worker_artifacts`. Промпт
этого шага — тот же самый reference-файл, что используется для per-repo пунктов в шаге 8 (несмотря на то что
шаг 10 логически — не «ещё один repo-scoped проход», а единственный шаг, который видит **весь** накопленный
набор фич сразу, после того как все репозитории уже проанализированы и все `open_questions` закрыты в
интервью). Reference-файл ([checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md#L79-L94))
содержит раздел «Проверка согласованности и правка артефактов», но он написан как чек-лист для одного
репозитория (сверка `features-index.md` с только что обработанным репозиторием), а не как явное задание
«пройтись по всем фичам всех репозиториев разом и проверить полноту/непротиворечивость/пропуски по всему
продукту». Из-за этого нет гарантии, что: (a) каждая обнаруженная в шаге 7 предметная область (`domains` из
`assess_scope_and_domains`) отражена хотя бы одной фичей или явно закрыта как «не продуктовая capability»; (b)
между фичами разных репозиториев нет противоречий (два файла описывают один и тот же бизнес-поток
по-разному); (c) не осталось repository, которое анализировался, но ни разу не упомянут ни в одной фиче и ни
в `support-repositories.md`.

## Принятые решения по архитектуре

- **Без новых физических узлов графа.** Обе проблемы решаются на уровне routing-конфигурации и промпт-контента
  (reference-файлов), не топологии `graph.py` — согласуется с тем, что шаг 8 уже расщеплён на repo/item-ноды
  ([2026-07-21-analyze-repositories-per-item-nodes.md](2026-07-21-analyze-repositories-per-item-nodes.md)) и
  дальнейшее дробление не требуется: «обязательность» пункта чек-листа — это вопрос `route_checklist_items`,
  а «финальная сверка» в шаге 10 — вопрос содержания промпта одного уже существующего LLM-вызова.
- **`feature_discovery_and_updates`/`features_index_updates` → в `_ALWAYS_ROUTED_CHECKLIST_ITEMS`.** Простое,
  локальное изменение множества в `signal_routing.py` — оба пункта чек-листа обрабатываются на **каждом**
  репозитории независимо от diff severity (аналогично тому, как уже гарантированы
  `architecture_artifact_updates`/`repository_consistency_review`). `NO_SIGNAL` severity (репозиторий без
  изменений за окно) — исключение по смыслу: если diff пуст, синтезировать по нему новую capability нечего,
  поэтому `NO_SIGNAL`-ветка `route_checklist_items` (строка 108-109) не трогается — она уже осознанно
  сужает набор до `_NO_SIGNAL_CONFIRMATION_ITEM` (`repository_consistency_review`) и не подмешивает
  `_ALWAYS_ROUTED_CHECKLIST_ITEMS`. Для `NOT_STARTED`/`BASELINE_MISSING`/`INVALID_RANGE` (`FULL_REQUIRED`) и
  `BROAD` — оба пункта и так уже входили в полный чек-лист, изменение ничего не меняет.
- **Место в порядке выполнения — без изменений.** В `CHECKLIST_ITEM_TO_REFERENCE`
  ([prompts.py:55-77](../../back/app/workflows/init_arch/prompts.py#L55-L77)) `feature_discovery_and_updates`/
  `features_index_updates` уже идут после всех технических пунктов (структура, entrypoints, контракты,
  хранилища, домены, интеграции, тесты, глоссарий) и перед `architecture_artifact_updates`/
  `repository_consistency_review` — то есть по порядку словаря они и так исполняются в конце обработки
  одного репозитория, до двух финальных always-routed пунктов сверки. Менять порядок словаря не требуется;
  сам факт «обязательности» (первое решение) — единственное, чего не хватало для «в конце шага 8 по каждому
  репозиторию».
- **`refine_features` (нода 10) получает отдельный reference-раздел под финальную сверку**, а не новый
  `task_kind`/новый узел. Добавляется новая секция «Часть 3: финальная сверка по всему реестру фич» в конец
  [checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md),
  которая явно инструктирует агента: (а) перечитать **все** файлы `features/*.md` и `features-index.md` целиком
  (не только те, что могли быть тронуты последним вызовом), (б) сверить с `architecture/domain-map.yaml`
  (домены из шага 7, см. ноду 7 в [init-graph-reference.md](../workflows/init-graph-reference.md)) — у каждого
  домена должна быть хотя бы одна фича или явная пометка «инфраструктурный домен без продуктовой capability»;
  (в) сверить со списком проанализированных репозиториев в `session.repositories` — каждый должен быть
  упомянут либо в `sources`/`repositories` какой-то фичи, либо в `architecture/support-repositories.md`; (г)
  найти и устранить противоречия между фичами (один и тот же бизнес-поток описан по-разному в двух файлах,
  расходящийся статус реализации для одной и той же трассировки); (д) починить найденные несоответствия
  прямо в файлах, а не только зафиксировать их как `open_questions` (если правка требует ответа пользователя,
  которого уже не будет — `interview_user` к этому моменту уже пройден, см. граф — тогда фиксировать в
  `open-questions.md` с пометкой, что вопрос всплыл после интервью, и решение оставлено на усмотрение
  следующего temporal-окна). Это не создаёт нового узла графа — `node_refine_features` вызывает
  `_run_step_worker` один раз с тем же `StepId.REFINE_FEATURES`, просто промпт (через существующий reference)
  теперь явно требует пройтись по всему накопленному состоянию, а не только по дельте последнего репозитория.
- **`STEP_TO_REFERENCE["refine_features"]` не меняется** (по-прежнему указывает на
  `checklist-features-and-index.md`, [prompts.py:47](../../back/app/workflows/init_arch/prompts.py#L47)) —
  расширяется контент самого файла, а не путь к нему; так `_build_prompt`
  ([prompts.py:240](../../back/app/workflows/init_arch/prompts.py#L240)) не требует изменений.
- **Важное уточнение (обнаружено при повторной проверке `prompts.py`): этот же файл уже подключён к шагу 8
  дважды.** `CHECKLIST_ITEM_TO_REFERENCE["feature_discovery_and_updates"]` и
  `CHECKLIST_ITEM_TO_REFERENCE["features_index_updates"]`
  ([prompts.py:69-70](../../back/app/workflows/init_arch/prompts.py#L69-L70)) указывают на тот же
  `checklist-features-and-index.md`, что и `STEP_TO_REFERENCE["refine_features"]`. Значит «Часть 3»
  (финальная сверка, Фаза 3) окажется в промпте LLM и во время обработки этих двух пунктов чек-листа внутри
  `analyze_repositories_item` — файл общий, `build_step_prompt()` не подставляет разный контент под разные
  вызовы. Разграничение «выполнять только в `refine_features`» не может опираться на подразумеваемый
  контекст — оно должно быть завязано на конкретный, видимый агенту сигнал в самом промпте: строку
  ``Шаг: `{step_value}` `` ([prompts.py:290](../../back/app/workflows/init_arch/prompts.py#L290)), которая
  детерминированно равна `analyze_repositories` для обоих feature-пунктов чек-листа шага 8 (`checklist_item_id`
  влияет только на выбор reference-файла, [prompts.py:241-242](../../back/app/workflows/init_arch/prompts.py#L241-L242),
  но сам никуда в текст промпта не попадает — отдельный, не связанный с этой задачей пробел) и `refine_features`
  для шага 10. Формулировка «Части 3» (Фаза 3) должна явно ссылаться на эту строку, а не на абстрактное «когда
  используется как refine_features» — например: «Выполняй этот раздел только если строка `Шаг:` выше в этом
  промпте равна `refine_features`; если она равна `analyze_repositories` — раздел пропусти целиком».

## Фазы

### Фаза 1 — обязательные feature-пункты чек-листа на каждом репозитории `[x]`

В `domain/signal_routing.py`:

```python
_ALWAYS_ROUTED_CHECKLIST_ITEMS: typing.Final[frozenset[str]] = frozenset(
    {
        "architecture_artifact_updates",
        "repository_consistency_review",
        "feature_discovery_and_updates",
        "features_index_updates",
    }
)
```

Тесты в `test_signal_routing.py` (рядом с `test_local_routes_impacted_categories_plus_always_routed`,
`test_local_with_unmatched_paths_routes_only_always_routed`, `test_no_signal_routes_only_consistency_review`):

- `LOCAL`-diff с путями, не задевающими вообще ни одной категории (например, `["docs/readme.md"]`) →
  routed-набор теперь содержит 4 always-routed пункта (было 2), в том числе оба feature-пункта.
- `LOCAL`-diff с путями, задевающими одну техническую категорию (например, `["services/checkout/x.py"]`) →
  routed-набор = always-routed (4) + `business_flow_orchestration`, порядок соответствует
  `CHECKLIST_ITEM_TO_REFERENCE`.
- `NO_SIGNAL` (пустой diff / `CommitRangeStatus.NO_CHANGES`) → routed-набор **не** меняется, по-прежнему
  только `repository_consistency_review` (проверить явно, что фикс из этой фазы не задевает `NO_SIGNAL`-ветку
  — она читает `_NO_SIGNAL_CONFIRMATION_ITEM`, не `_ALWAYS_ROUTED_CHECKLIST_ITEMS`).
- `FULL_REQUIRED`/`BROAD` — без изменений (возвращают весь список, регрессия исключена по построению функции).

**Мини-отчёт**: реализовано без отклонений от плана. `_ALWAYS_ROUTED_CHECKLIST_ITEMS` в `signal_routing.py`
расширен с 2 до 4 элементов (`feature_discovery_and_updates`/`features_index_updates` добавлены рядом с
`architecture_artifact_updates`/`repository_consistency_review`); `_NO_SIGNAL_CONFIRMATION_ITEM`-ветка не
трогалась. В `test_signal_routing.py`: `_ALL_ITEMS` дополнен обоими feature-пунктами (в позиции, аналогичной
их месту в реальном `CHECKLIST_ITEM_TO_REFERENCE` — после технических пунктов, перед
`architecture_artifact_updates`); `test_local_routes_impacted_categories_plus_always_routed` дополнен двумя
assert'ами на наличие feature-пунктов; `test_local_with_unmatched_paths_routes_only_always_routed` обновлён —
теперь ожидает список из 4 элементов вместо 2, с сохранением порядка `_ALL_ITEMS`; добавлен новый тест
`test_no_signal_does_not_route_feature_items`, явно фиксирующий, что `NO_SIGNAL`-ветка не подмешивает
feature-пункты (только `repository_consistency_review`, как и раньше) — это прямая проверка того самого
разграничения, которое было принято в разделе «Принятые решения». `pytest
tests/workflows/init_arch/domain/test_signal_routing.py`: 15 passed (было 14 тест-функций в файле до правок,
+1 новая функция `test_no_signal_does_not_route_feature_items`; правки в двух существующих тестах — не новые
функции), 0 регрессий.

### Фаза 2 — уточнение reference-документа: обязательность не зависит от diff severity `[x]`

В [checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md),
в начало (после текущего вводного абзаца, до «Часть 1»), добавить короткий абзац: этот пункт чек-листа
выполняется на **каждом** репозитории с непустым diff (не пропускается diff-роутингом по severity, в отличие
от большинства других пунктов) — если репозиторий не добавил и не изменил ни одной продуктовой capability,
явно зафиксировать это как вывод («по этому репозиторию новых/изменённых фич нет») в `notes`, а не молча
оставить пункт без содержательного результата.

Синхронизировать копии этого файла в `init-repo-arch-skill/references/` и
`update-repo-arch-skill/references/`, если они читаются оттуда же (см. одноимённые файлы, обнаруженные при
поиске — сверить, действительно ли они используются рантаймом `arch-docs/back` через какой-то механизм
синхронизации ассетов, или это независимые копии для соответствующих skill-паков; расхождение задокументировать,
если синхронизации нет).

**Мини-отчёт**: абзац про обязательность добавлен в `checklist-features-and-index.md`
([shared_assets/init_arch/references/checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md))
сразу после вводного блока, перед первым `---`, как и было запланировано. Проверка синхронизации: `diff` между
этим файлом и одноимёнными копиями в `init-repo-arch-skill/references/` и `update-repo-arch-skill/references/`
показал, что копии — обычные независимые файлы (не symlink, `file` подтверждает "regular Unicode text"), и они
уже расходились с версией `arch-docs/back` **до** этой правки (например, пункт 2 «Часть 1» в
`arch-docs/back`-версии описывает frontmatter/секции файла фичи инлайн, а в обеих skill-пак копиях —
отсылкой к `assets/feature-template.md`). Значит, рантайм `arch-docs/back` не читает эти копии, и синхронизация
между тремя копиями этого файла в принципе не поддерживается никаким механизмом на сегодня — это pre-existing
расхождение, не вызванное текущей задачей. В скоуп этой фазы правка синхронизации не входит (см. «Out of
scope»), поэтому копии в `init-repo-arch-skill`/`update-repo-arch-skill` намеренно не тронуты.

### Фаза 3 — финальная сверка по всем фичам в `refine_features` `[x]`

В [checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md)
добавить новый раздел «Часть 3: финальная сверка по всему реестру фич» (после текущего «Подводные камни»),
применимый только когда шаг вызывается как `refine_features` (нода 10), а не как per-repo пункт чек-листа в
шаге 8 — сформулировать это разграничение прямо в тексте раздела (например: «Следующий раздел применяется,
когда этот референс используется в шаге `refine_features` — после того как все репозитории проанализированы
и все открытые вопросы интервью закрыты; при вызове как пункт чек-листа `feature_discovery_and_updates`/
`features_index_updates` внутри анализа одного репозитория — не выполнять»):

1. Перечитать целиком `features-index.md` и каждый файл `features/*.md` — не только те, что менялись в
   последнем LLM-вызове.
2. Сверить с `architecture/domain-map.yaml` (результат `assess_scope_and_domains`, нода 7): для каждого
   домена — есть хотя бы одна фича с `domain: <domain>` в frontmatter, либо явная пометка в
   `architecture/support-repositories.md`/`open-questions.md`, что это не продуктовый домен.
3. Сверить с полным списком репозиториев в `session.repositories`: каждый репозиторий упомянут либо в
   `repositories`/`sources` какой-нибудь фичи, либо в `architecture/support-repositories.md`. Ничего не должно
   выпасть из поля зрения молча.
4. Найти противоречия между фичами: один бизнес-поток описан по-разному в двух файлах, статус реализации
   (`implemented`/`partial`/`unknown`) расходится с фактической трассировкой в другом месте, ссылки на один
   контракт/хранилище дают несовместимые описания.
5. Исправить найденные несоответствия прямо в файлах. Если правка требует уточнения у пользователя (интервью
   уже пройдено на этом этапе) — зафиксировать в `open-questions.md` с пометкой `discovered_at: refine_features`,
   не блокируя шаг.
6. Обновить `features-index.md`, если сверка обнаружила фичи без строки в реестре или строки без файла.

Файл `nodes.py`/`prompts.py` не меняются в этой фазе (см. «Принятые решения» — reference расширяется, путь и
код вокруг вызова остаются как есть).

**Мини-отчёт**: раздел «Часть 3: финальная сверка по всему реестру фич» добавлен в
[checklist-features-and-index.md](../../back/app/workflows/shared_assets/init_arch/references/checklist-features-and-index.md)
после «Подводные камни», с отдельным `---` перед ним. Условие применимости сформулировано буквально через
сигнал из промпта — первая строка раздела: «Выполняй этот раздел только если строка `Шаг:` выше в этом
промпте равна `refine_features`... Если она равна `analyze_repositories`... — раздел пропусти целиком», что
дословно соответствует уточнению из «Принятых решений» про строку ``Шаг: `{step_value}` `` в
[prompts.py:290](../../back/app/workflows/init_arch/prompts.py#L290) — это привязка к конкретному видимому
агенту тексту промпта, а не к подразумеваемому контексту. Все 6 пунктов из плана перенесены в чек-лист без
отклонений (перечитать все features целиком → сверка с domain-map.yaml → сверка со списком репозиториев →
поиск противоречий → правка на месте/фиксация в open-questions с `discovered_at: refine_features` → апдейт
features-index.md). `nodes.py`/`prompts.py` не менялись, как и предполагалось — `STEP_TO_REFERENCE` и
`CHECKLIST_ITEM_TO_REFERENCE` по-прежнему указывают на тот же файл, расширился только его контент.
Синхронизация копий в `init-repo-arch-skill`/`update-repo-arch-skill` не выполнялась по той же причине, что и
в Фазе 2 (независимые, уже разошедшиеся копии, вне скоупа).

### Фаза 4 — актуализация документации `[x]`

- [init-graph-reference.md](../workflows/init-graph-reference.md), нода 8 (раздел «8.
  `analyze_repositories`/`analyze_repositories_item`»): в таблице reference-файлов и в тексте про
  `route_checklist_items` уточнить, что `feature_discovery_and_updates`/`features_index_updates` теперь в
  числе always-routed пунктов (наравне с `architecture_artifact_updates`/`repository_consistency_review`),
  со ссылкой на эту спеку.
- [init-graph-reference.md](../workflows/init-graph-reference.md), нода 10 (`refine_features`): дополнить
  описание — шаг теперь явно включает финальную сверку по всему накопленному реестру фич (не только
  синтез новых), со ссылкой на «Часть 3» reference-файла и на эту спеку.
- Эта спека — статус `done` после Фаз 1-4.

**Мини-отчёт**: [init-graph-reference.md](../workflows/init-graph-reference.md) обновлён в двух местах. (1)
Нода 8 — после абзаца про домены (конец описания `analyze_repositories_item`, перед таблицей reference-файлов)
добавлен абзац «Обязательные пункты независимо от diff severity»: объясняет расширение
`_ALWAYS_ROUTED_CHECKLIST_ITEMS`, почему раньше `LOCAL`-diff мог пропускать feature-пункты (они не входили ни
в одну категорию `_PATH_SIGNAL_CATEGORIES`), и что для `NO_SIGNAL` поведение не изменилось — со ссылкой на эту
спеку. (2) Нода 10 — в описании «Что делает» добавлено упоминание финальной сверки; в блоке «LLM» добавлен
абзац о том, что reference-файл общий с шагом 8, разграничение идёт по строке `Шаг:` в промпте, и что нода 10
(в отличие от repo-scoped ноды 8) видит весь накопленный реестр фич сразу и обязана проверить согласованность
с доменами (нода 7) и списком репозиториев — со ссылкой на эту спеку. Правки не трогают mermaid-диаграмму
(топология графа не менялась) и остальные разделы нод 8/10 («Файлы», «В базе», «На выходе» и т.д.) — они
по-прежнему точны, изменения этой задачи не затрагивают код вокруг вызовов `_run_step_worker`.

## Тестирование (сквозной критерий)

- Фаза 1 — юнит-тесты `test_signal_routing.py`, покрывающие все 4 ветки `DiffSeverity` с учётом расширенного
  `_ALWAYS_ROUTED_CHECKLIST_ITEMS` (см. Фазу 1). Регрессионных изменений в существующих тестах на
  `route_checklist_items` не ожидается, кроме тех, что явно проверяли старый размер always-routed набора
  (их ожидаемые списки нужно обновить на 4 элемента вместо 2, если такие проверки жёстко фиксируют длину/состав).
- Фазы 2-3 — изменения только в markdown reference-файлах, без исполняемого кода; отдельных unit-тестов не
  требуется, но стоит прогнать существующий сьют (`pytest`), чтобы убедиться, что ничего не парсит содержимое
  этих файлов программно за пределами `_load_shared_asset`.
- Цель по покрытию дельты — 100% для изменённого Python-кода (`pylines`-гайдлайн проекта); markdown-контент
  не покрывается coverage-метрикой по построению.

## Критерии готовности

- `route_checklist_items` возвращает `feature_discovery_and_updates`/`features_index_updates` для **любого**
  репозитория с непустым diff (`LOCAL`/`BROAD`/`FULL_REQUIRED`), независимо от того, какие категории задели
  его пути; для `NO_SIGNAL` — поведение не меняется (по-прежнему только `repository_consistency_review`).
- `checklist-features-and-index.md` явно фиксирует: (а) обязательность per-repo пунктов независимо от diff
  severity; (б) отдельный раздел финальной сверки, применяемый только в `refine_features`.
- `init-graph-reference.md` (ноды 8 и 10) отражает оба изменения со ссылкой на эту спеку.
- Существующий тестовый сьют — 0 регрессий после Фазы 1. Подтверждено:
  `pytest tests/workflows/init_arch` — 265 passed, 1 xfailed, 0 регрессий; `ruff check`/`ruff format --check`
  на изменённых файлах (`signal_routing.py`, `test_signal_routing.py`) чисты.

## Out of scope

- Отдельный физический узел графа для финальной сверки фич (например, `refine_features_review` как ещё один
  physical node с собственным чекпоинтом) — не требуется, т.к. `refine_features` уже один LLM-вызов, который
  видит всё накопленное состояние; дробление имело бы смысл только при повторяющемся цикле по фичам (как
  `analyze_repositories_item` по чек-листу), чего сейчас нет и не запрашивалось.
- Автоматическая (не-LLM) программная проверка полноты доменов/репозиториев (детерминированный lint,
  аналогичный `run_knowledge_lint`) — возможное будущее усиление, если LLM-сверки окажется недостаточно на
  практике; вне скоупа этой задачи, которая ограничивается routing-конфигурацией и содержанием промптов.
- Синхронизация копий `checklist-features-and-index.md` в других skill-паках (`init-repo-arch-skill`,
  `update-repo-arch-skill`), если выяснится, что они независимы от ассетов `arch-docs/back` и обслуживают
  отдельный продукт/repo — фиксируется как отдельный вопрос в Фазе 2, не разрешается в этой спеке заранее.
