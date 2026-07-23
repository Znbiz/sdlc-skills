# Проекты (Conversation): единая директория, репозитории и страница проекта в стиле VS Code

## Проблема

Сейчас у каждого `init_arch` workflow run есть своя строка в БД (`workflow_runs.workflow_id`,
[`app/db/models.py:64-91`](../../back/app/db/models.py#L64-L91)), но **нет своей директории на диске**:

- `workspace_dir` — это путь, который **пользователь вводит в форме** (`InitArchForm`,
  [`front/src/features/workflow/init-arch-form.tsx:7,24`](../../front/src/features/workflow/init-arch-form.tsx#L7)),
  по умолчанию `/workspace` (константа `DEFAULT_WORKSPACE_DIR`). Ничего не мешает двум разным
  workflow (двум разным `workflow_id`) использовать один и тот же `workspace_dir` — единственная
  защита от коллизии есть только в `resume_init_arch_workflow_from_snapshot()`
  ([`app/services/init_arch_workflow.py:1214-1226`](../../back/app/services/init_arch_workflow.py#L1214-L1226))
  и явно не cross-process (комментарий в коде это подтверждает).
- `raw_workspace_dir` (куда клонируются анализируемые репозитории, `_clone_repositories()`,
  [`app/workflows/init_arch/nodes.py:329-360`](../../back/app/workflows/init_arch/nodes.py#L329-L360))
  всегда вычисляется как `<workspace_dir>/.temp` (`_resolve_init_arch_paths()`,
  [`app/services/init_arch_workflow.py:1061-1085`](../../back/app/services/init_arch_workflow.py#L1061-L1085)) —
  общий на весь `workspace_dir`, не привязан к `workflow_id`.
- Директория `/workspace` создаётся один раз при сборке образа (`Dockerfile:29`:
  `mkdir -p /workspace && chown appuser:appuser /workspace`) как единый named volume
  (`docker-compose.yml`, `workspace:/workspace`); поддиректории появляются лениво только когда
  что-то реально в них пишет (первый клон, первая запись progress-файла).

**У проекта (а не у отдельного run) нет никакой идентичности.** `WorkflowRunModel.workflow_name`
([`app/db/models.py:73`](../../back/app/db/models.py#L73)) — это не название, а тип workflow
(`"init_arch"` всегда, аналог enum-дискриминатора). `InitArchInput.product_name` ближе всего к
названию, но живёт внутри сессии конкретного run
(`WorkflowSessionRecord.product_name`,
[`app/workflows/init_arch/domain/models.py:186`](../../back/app/workflows/init_arch/domain/models.py#L186)) —
не там, где реально нужна идентичность: сегодняшняя страница называется **"Init Workflow"**
([`front/src/app/app-shell.tsx:8`](../../front/src/app/app-shell.tsx#L8)), как будто пользователь
управляет запусками конкретного типа workflow, а не проектами. Список
([`WorkflowList`](../../front/src/features/workflow/workflow-list.tsx)) показывает только
`conversation_id` — сырой UUID, невозможно на глаз отличить один проект от другого; страница
конкретного run (`InitWorkflowPage`) тоже не показывает ничего, кроме `conversation_id` в URL —
заголовок статичный `<h1>Init Workflow</h1>`.

**`repo_list` живёт не на своём уровне.** Список репозиториев — это входной параметр конкретного
запуска (`InitArchInput.repo_list`, парсится в `start_init_arch_workflow()` через
`_parse_repo_list_entry()`,
[`app/services/init_arch_workflow.py:1061-1067`](../../back/app/services/init_arch_workflow.py#L1061-L1067)),
а не настройка проекта. Из-за этого: (а) при каждом новом run (в т.ч. после restart) список нужно
вводить заново — спасает только `previous_init_input`-prefill конкретно для `init_arch`; (б) список
репозиториев нигде не хранится независимо от того, был ли вообще хоть один run; (в) если в будущем
появится второй тип workflow, работающий с тем же набором репозиториев (например `update_arch` не
как одиночный `CliTask`, а как полноценный граф-workflow), ему придётся либо дублировать `repo_list`
в своём собственном input, либо выдумывать способ прочитать его из последнего `init_arch` run того
же `conversation_id` — оба варианта хрупкие.

**Число одновременных инстансов workflow на conversation нигде не объявлено.** В коде нет понятия
"сколько одновременных `workflow_type=X` run допустимо в рамках одного `conversation_id`" — ни как
декларативного параметра, ни как проверки. Для `init_arch` это в принципе не должно быть больше
одного (см. раздел "Инвариант"), но это нигде не задано явно и не проверяется
(`create_response_async()`,
[`app/services/init_arch_workflow.py:581-593`](../../back/app/services/init_arch_workflow.py#L581-L593),
просто создаёт run без проверки существующих). Для будущих типов workflow (например `update_arch`)
предполагается обратное — множество одновременных инстансов допустимо и полезно, и это тоже нужно
уметь объявить, а не зашивать в условия отдельными `if workflow_type == ...`.

**Файловый браузер, репозитории и управление run разбросаны по разным местам.** Похожий на желаемый
UI **уже есть** — вкладка **Docs**
([`front/src/features/docs/docs-page.tsx`](../../front/src/features/docs/docs-page.tsx)) с
дерево-слева/контент-справа для `arch_repo_dir`, backed by
[`app/api/rest/docs.py`](../../back/app/api/rest/docs.py) +
[`app/services/docs_browser.py`](../../back/app/services/docs_browser.py) — но она (а) жёстко
привязана к `arch_repo_dir` конкретного `response_id`, требует вручную ввести `response_id` на
отдельной странице, никак не связана с проектом; (б) показывает только уже сгенерированную
документацию, не сырые клоны/весь workspace; (в) на ней нет ни списка репозиториев, ни управления
запуском workflow. Управление run (`InitWorkflowPage`) — отдельная страница без файлового браузера
вообще. Пользователю, чтобы поработать с одним проектом, приходится прыгать между `/workflows/init/
{id}` и вручную введённым `response_id` на `/docs`.

## Цель

1. Каждый проект (`conversation_id`) получает собственную, предсказуемую директорию на диске под
   `/workspace` — без коллизий между разными проектами и без необходимости вручную придумывать/вводить
   уникальный путь; документация (`arch_repo_dir`) внутри неё переживает restart и historical windows
   того же проекта.
2. Каждый отдельный run (`workflow_id`) внутри проекта получает свою поддиректорию для сырых клонов —
   без коллизий между параллельными/последовательными run одного и того же проекта.
3. Список репозиториев — **настройка conversation**, задаётся один раз и переиспользуется любым
   workflow, который запускается в рамках этого conversation (сегодня — только `init_arch`, в
   будущем — любой новый тип), а не параметр каждого отдельного run.
4. У проекта (не у отдельного run) есть название (`product_name`, теперь на conversation) — **не
   нужны человекочитаемые имена у отдельных workflow run**, идентичность целиком на уровне проекта.
5. Страница со списком переименована из "Init Workflow" в **"Проекты"**: показывает название
   проекта, репозитории, статус/шаг/дату старта последнего run — не только `conversation_id`.
6. Страница проекта (заменяет сегодняшнюю `InitWorkflowPage`) устроена как в VS Code — три колонки:
   дерево файлов проекта и список репозиториев слева, содержимое файла по центру, управление
   workflow (выбор/запуск run, статус, диалог с пользователем, лог событий) справа.
7. Вкладка Docs переиспользует то же название проекта вместо сырого `response_id` при выборе, что
   смотреть.
8. Число одновременных активных инстансов workflow одного типа в рамках одного conversation —
   **декларативный параметр в коде** (для `init_arch` — 1, для будущих типов может быть больше или
   не ограничено), проверяемый одним общим механизмом.

Не цель: редактирование файлов через браузер (только просмотр, как и в существующем Docs-вьюере),
изменение `product_name` после создания, retention/автоочистка старых директорий, серверная
пагинация/фильтрация списка проектов, одновременный просмотр нескольких run в нескольких колонках
(только переключатель — один выбранный run в правой колонке за раз), редизайн самой формы параметров
`init_arch` (движок/таймаут/`analysis_scope` остаются как есть, просто переезжают в новую колонку).

## Текущая архитектура (для контекста)

```text
_resolve_init_arch_paths(workspace_dir, arch_repo_dir):
    workspace_path      = resolve(workspace_dir)                          # пользовательский путь
    raw_workspace_path   = resolve(workspace_path / ".temp")               # общий на весь workspace_dir
    arch_repo_path       = resolve(arch_repo_dir) or (workspace_path / "arch-doc")
    # guard: raw_workspace_path не может содержать arch_repo_path
    # guard: arch_repo_path обязан быть внутри workspace_path (или наоборот, или равен)
    return workspace_path, arch_repo_path, raw_workspace_path
```

Вызывается из `start_init_arch_workflow()`
([`app/services/init_arch_workflow.py:1133-1157`](../../back/app/services/init_arch_workflow.py#L1133-L1157))
и `resume_init_arch_workflow_from_snapshot()`
([`app/services/init_arch_workflow.py:1193-1281`](../../back/app/services/init_arch_workflow.py#L1193-L1281)).
`workflow_id` (`str(uuid.uuid4())`) уже генерируется **до** резолва путей в `start_init_arch_workflow()` —
значит его можно использовать при построении пути без изменения порядка операций.

**Важный нюанс, который ограничивает решение**: `arch_repo_dir` — это не эфемерный scratch, а
**целевой репозиторий с документацией**, который явно рассчитан на переиспользование между
запусками. Это видно по `restart_init_arch_workflow()` → `previous_init_input`
(`ConversationResponse.previous_init_input`,
[`app/api/rest/conversations.py:49-54`](../../back/app/api/rest/conversations.py#L49-L54)): после
restart форма предзаполняется **тем же** `workspace_dir`/`arch_repo_dir`/`repo_list`, чтобы новый
run продолжил писать в тот же `arch-doc`. Если бы `arch_repo_dir` был жёстко привязан к
`workflow_id`, restart каждый раз создавал бы новый пустой репозиторий документации — это ломает
основной сценарий работы сервиса (historical windows, накопление документации между run). Поле
`previous_init_input` определено в `PreviousInitInputResponse`
([`app/api/rest/conversations.py:63-69`](../../back/app/api/rest/conversations.py#L63-L69)).

Второй существующий прецедент — двухколоночный layout вкладки Docs
(`grid-template-columns: minmax(220px, 300px) 1fr`,
[`front/src/features/docs/docs-page.module.css:9`](../../front/src/features/docs/docs-page.module.css#L9)) —
именно его расширяем до трёх колонок для страницы проекта (раздел 5).

## Решение: изоляция в два уровня — conversation (проект) и workflow (run)

Нужны **оба** уровня одновременно, и они не конфликтуют, если разнести их по разным сегментам пути:

- **`conversation_id` — граница проекта.** Один `conversation` = один проект = одна стабильная папка
  на диске, автоматически выводимая из `conversation_id`, без необходимости вручную придумывать и
  каждый раз вводить одинаковый путь. Два разных проекта физически не могут столкнуться, потому что
  `conversation_id` уникален. `arch_repo_dir` (накапливаемая документация) живёт **внутри** этой
  папки и переживает любое число restart/historical-windows того же проекта — именно то поведение,
  которое сегодня обеспечивает только `previous_init_input`-prefill (см. выше), но теперь без
  необходимости пользователю помнить/вбивать путь заново. Проект — это и есть единица идентичности:
  название (раздел 3), репозитории (раздел 2) и список run (раздел 5) висят на `conversation_id`, а
  не на отдельных `workflow_id`.
- **`workflow_id` — граница одного прогона внутри проекта.** Сырые клоны репозиториев и
  `repo-initialization-progress.yaml` для конкретного `run` (`workflow_id`) живут в своей
  поддиректории **внутри** папки проекта — так два последовательных run одного и того же проекта
  (после restart) не задевают клоны друг друга. У отдельного run **не должно быть своего названия** —
  это просто точка в истории проекта (см. раздел 4 про run-селектор), различается статусом/шагом/датой,
  не именем.

Итоговая раскладка на диске:

```text
/workspace/<conversation_id>/                       # project root — стабилен для всего проекта
  arch-doc/                                          # arch_repo_dir по умолчанию — переживает restart
  runs/<workflow_id>/                                # run_workspace_dir — свой на каждый run
    <repository_name>/                               # сырые git-клоны именно этого run
    repo-initialization-progress.yaml
```

Единственное, что здесь осознанно приносится в жертву — переиспользование уже склонированных
репозиториев между run одного и того же проекта: каждый новый `workflow_id` клонирует репозитории
заново в свою `runs/<workflow_id>/`, даже если такой же репозиторий уже лежит в
`runs/<другой workflow_id>/` того же проекта. Для больших репозиториев это ощутимо увеличивает время
повторного старта — стоит явно измерить и, при необходимости, добавить отдельным быстрым улучшением
copy-on-write/`git clone --reference` от предыдущего run того же `conversation_id` (не в этой
итерации).

### Инвариант: декларативный лимит инстансов на пару (workflow_type, conversation)

Общая `arch-doc/` на весь проект работает безопасно только при одном допущении: **на один
`conversation_id` в любой момент времени активен максимум один `init_arch` run** — иначе два run
одновременно пишут в одну и ту же `arch_repo_dir` без какой-либо координации (гонки записи файлов,
конфликтующие git-коммиты, если документация версионируется). Продуктово это и так предполагалось
(один прогон = один проход анализа проекта; пауза/остановка/продолжение — не параллельный запуск, а
управление жизненным циклом того же самого прогона), но **сегодня это нигде не проверяется на
бэкенде и не объявлено декларативно**:

- `create_response_async()` ([`app/services/init_arch_workflow.py:581-593`](../../back/app/services/init_arch_workflow.py#L581-L593))
  вызывает `start_init_arch_workflow()` без какой-либо проверки на уже существующий активный run для
  того же `conversation_id`; ветвление между `init_arch`/`update_arch`/`query` там сегодня —
  просто `if workflow_type == "..."`, без общего для всех типов слоя политик.
- Единственный существующий guard на дублирование — в `resume_init_arch_workflow_from_snapshot()`
  ([`app/services/init_arch_workflow.py:1214-1226`](../../back/app/services/init_arch_workflow.py#L1214-L1226)) —
  сравнивает по `arch_repo_dir`, а не по `conversation_id`, и применяется только к пути
  восстановления из YAML-снапшота, не к обычному созданию run через API.
- На фронте `InitWorkflowPage` показывает форму создания run только когда
  `!activeResponse` (нет активного run для conversation) — это мягкое, чисто клиентское ограничение:
  два браузерных таба, повторный запрос после сетевого сбоя, или прямой вызов API легко его обходят.
- `_active_conversation_record()` ([`app/services/init_arch_workflow.py:355-360`](../../back/app/services/init_arch_workflow.py#L355-L360))
  при нескольких `WorkflowRecord` для одного `conversation_id` в реестре молча берёт **только
  последний обновлённый** — если два run окажутся одновременно активны, второй станет невидимым в
  API/UI, но продолжит работать и писать на диск.

**Предлагается небольшой декларативный реестр** конфигов по `workflow_type`, а не хардкод "для
`init_arch` максимум 1":

```python
@dataclasses.dataclass(frozen=True)
class WorkflowTypeConfig:
    # None = не ограничено. Для init_arch — 1: пауза/остановка/продолжение/restart уже дают полный
    # контроль над жизненным циклом одного прогона, параллельные инстансы того же типа conversation
    # не нужны и опасны для общей arch_repo_dir. Для будущих типов (например update_arch как
    # полноценный граф-workflow, а не одиночный CliTask) может быть None или другое число.
    max_concurrent_instances_per_conversation: int | None
    # Сигнал для остальной части этой спеки (разделы 2 и далее) — читает ли этот тип workflow
    # список репозиториев conversation при старте.
    uses_conversation_repositories: bool


WORKFLOW_TYPE_REGISTRY: typing.Final[dict[str, WorkflowTypeConfig]] = {
    "init_arch": WorkflowTypeConfig(
        max_concurrent_instances_per_conversation=1,
        uses_conversation_repositories=True,
    ),
    # Будущие типы добавляются сюда — например:
    # "update_arch": WorkflowTypeConfig(max_concurrent_instances_per_conversation=None, ...),
}
```

`create_response_async()` перед диспатчем на `start_init_arch_workflow()`/будущие типы делает одну
общую проверку: если у `WORKFLOW_TYPE_REGISTRY[workflow_type].max_concurrent_instances_per_conversation`
задано число, и среди активных (`RUNNING`/`PAUSED`/`INTERRUPTED`) `WorkflowRecord` для этого
`conversation_id` **того же `workflow_type`** уже не меньше этого числа — `409 Conflict`
(`WorkflowConflictError`, тот же тип ошибки, что уже используется для конфликта по `arch_repo_dir`).
Тип, отсутствующий в реестре, по умолчанию трактуется как `max_concurrent_instances_per_conversation=1`
(безопасный дефолт). Это одновременно защищает общую `arch-doc/` для `init_arch` **сегодня** и даёт
готовый, настраиваемый в одном месте механизм для любых будущих типов workflow.

Практически сегодня в реестре нужен только `init_arch` — `update_arch`/`query` остаются одиночными
`CliTask` (таблица `cli_tasks`, не `workflow_runs`) и уже фактически неограничены по конкурентности;
формальная унификация `update_arch` под тот же `workflow_runs`-контур, где этот реестр начнёт
применяться и к нему — отдельная, более крупная задача не в рамках этой спеки (см. "Что не входит").

## Предлагаемый дизайн

### 1. Директория проекта и директория run

Два новых пути вместо одного пользовательского `workspace_dir`:

- `conversation_workspace_dir = <WORKSPACE_ROOT>/<conversation_id>/` — project root. Становится
  **дефолтным значением** поля `workspace_dir` в форме, вычисляемым автоматически по
  `conversation_id` (который уже известен на момент открытия страницы проекта — conversation
  создаётся отдельным вызовом `POST /conversations/` до формы создания run). Поле остаётся
  редактируемым (advanced override), но по умолчанию пользователю больше не нужно ничего вводить и
  придумывать уникальный путь самому.
- `run_workspace_dir = conversation_workspace_dir/runs/<workflow_id>/` — заменяет собой сегодняшний
  `raw_workspace_dir = <workspace_dir>/.temp` как место для:
  - сырых git-клонов анализируемых репозиториев (`_clone_repositories()`,
    [`nodes.py:329-360`](../../back/app/workflows/init_arch/nodes.py#L329-L360));
  - поиска репозитория при вычислении фактов о коммитах
    (`HistoricalPrepService._repository_path()`,
    [`historical.py:470-474`](../../back/app/workflows/init_arch/historical.py#L470-L474) — сначала
    ищет в `.temp/<name>`, затем в `workspace_dir/<name>`; после изменения — просто
    `run_workspace_dir/<name>`).

`run_workspace_dir` создаётся **eagerly**, в момент создания записи `workflow_runs` в
`start_init_arch_workflow()` — сразу после генерации `workflow_id`, до старта графа. `conversation_workspace_dir`
создаётся ещё раньше — в `create_conversation_async()`, одновременно со строкой `conversations` в БД.

`arch_repo_dir` по умолчанию — `conversation_workspace_dir/arch-doc` (как и сегодня, просто
`workspace_dir` теперь сам по себе уже уникален на проект, а не общий `/workspace`); остаётся
редактируемым полем для случая, когда документация должна писаться в путь вне `/workspace`.

Очистка: `restart_init_arch_workflow()` уже удаляет `raw_workspace_dir` с диска
(см. `delete_workflow_run()` + связанный docstring про cascade,
[`app/db/workflow_repo.py:307-319`](../../back/app/db/workflow_repo.py#L307-L319)) — после
изменения это становится удалением `run_workspace_dir` (`runs/<workflow_id>/`), не всей
`conversation_workspace_dir` — `arch-doc/` того же проекта не трогается, новый run после restart
получает новый `workflow_id` и, соответственно, новую `runs/<workflow_id>/`, но продолжает писать в
тот же `arch-doc/`.

### 2. Список репозиториев — настройка conversation, не run

Сегодня `ConversationModel` ([`app/db/models.py:48-61`](../../back/app/db/models.py#L48-L61))
хранит только `conversation_id`/`created_at`/`updated_at` — ни репозиториев, ни каких-либо ещё
настроек проекта. Список репозиториев целиком приходит через `InitArchInput.repo_list` только в
момент `POST /responses/` для `init_arch` и парсится через `_parse_repo_list_entry()`
([`app/services/init_arch_workflow.py:1061-1067`](../../back/app/services/init_arch_workflow.py#L1061-L1067))
прямо в `start_init_arch_workflow()`.

**Переносим источник истины на conversation:**

- Новая колонка `repositories: JSON` на `ConversationModel` — список записей вида
  `{repository_name, repository_url}` (та же нормализованная форма, что уже даёт
  `_parse_repo_list_entry()`, просто теперь считается один раз при настройке, а не при каждом run).
  Одна миграция вместе с названием проекта (раздел 3) —
  `migrations/versions/0007_add_conversation_project_settings.py` (`product_name` + `repositories`
  на `conversations`, следующая по номеру после `0006_add_workflow_path_metadata.py`).
- Новые REST-ручки:
  - `GET /conversations/{id}/repositories/` — текущий список.
  - `PUT /conversations/{id}/repositories/` — заменить список целиком.
  - `POST /conversations/{id}/repositories/` — добавить один (принимает `entry: str` — URL или голое
    имя, как и сегодняшний `InitArchInput.repo_list`-элемент).
  - `DELETE /conversations/{id}/repositories/{repository_name}/` — удалить один.
- `start_init_arch_workflow()` (и любой будущий тип из `WORKFLOW_TYPE_REGISTRY` с
  `uses_conversation_repositories=True`) больше не принимает `repo_list` как обязательный входной
  параметр — читает `conversation.repositories` в момент старта. `InitArchInput.repo_list` и
  `_INIT_ARCH_REQUIRED_FIELDS` ([`app/services/init_arch_workflow.py:63-73`](../../back/app/services/init_arch_workflow.py#L63-L73))
  теряют `repo_list` из обязательных полей run; вместо этого `create_response_async()` проверяет
  "у conversation настроен хотя бы один репозиторий" **до** старта — `422`
  (`WorkflowValidationError`), если список пуст.
- `previous_init_input`-prefill (`PreviousInitInputResponse.repo_list`,
  [`app/api/rest/conversations.py:63-69`](../../back/app/api/rest/conversations.py#L63-L69)) теряет
  смысл для `repo_list` конкретно (он больше не привязан к прошлому run) — поле можно убрать из
  `PreviousInitInputResponse` вообще.

**Разграничение с уже реализованным run-level add/remove.** В предыдущей итерации уже добавлены
`action_type: "add_repository"/"remove_repository"` на `POST /responses/{response_id}/actions/`
(мутируют `session.repositories` **конкретного** запущенного/приостановленного/прерванного run через
`graph.aupdate_state()`, ограничено ранними шагами). Это остаётся **тактической горячей правкой уже
идущего прогона** (сценарий "`clone_repositories` упал, нужно поправить один репозиторий без
полного restart") и не заменяется настройками conversation. Согласованность между двумя уровнями:
run-level `add_repository`/`remove_repository` **дополнительно** применяет то же изменение к
`conversation.repositories`, чтобы правка не терялась при следующем restart.

Где это живёт на новой странице проекта (раздел 5): **conversation-level** список репозиториев — в
**левой** колонке (настройка проекта, редактируется всегда), **run-level** тактическая правка
(уже реализованный `WorkflowRepositories`) — в **правой** колонке рядом со статусом конкретного
выбранного run (редактируется только пока этот run в подходящем статусе/шаге, как и сегодня).

### 3. Название проекта: `product_name` на conversation, не на run

Раз у отдельного run не должно быть человекочитаемого названия (см. "Решение" — только conversation
несёт идентичность), `product_name` логично поднимается с уровня сессии run на уровень conversation:

- Новая колонка `product_name: str | None` на `ConversationModel` (та же миграция, что и
  `repositories` — раздел 2).
- Задаётся в отдельном месте настроек проекта (левая колонка страницы проекта, раздел 5) —
  `PATCH /conversations/{id}/` с телом `{product_name: str}`. Не привязано к моменту запуска
  какого-либо run.
- Обратная совместимость для "быстрого старта": `InitArchInput.product_name` остаётся опциональным
  полем формы запуска — если указано и `conversation.product_name` ещё пусто, backend при старте run
  подтягивает его наверх, в `conversation.product_name` (тот же паттерн "sync forward", что и для
  run-level repo add/remove → conversation.repositories из раздела 2). Так пользователь, который
  ещё не настроил название проекта явно, но ввёл `product_name` в форме запуска, всё равно получает
  названный проект — без обязательного отдельного шага.
- `WorkflowSessionRecord.product_name` (сессия конкретного run) остаётся как есть — это по-прежнему
  нужно графу для промптов LLM; source of truth для отображения в UI — `conversation.product_name`.
- Никакого отдельного `run_label`/названия для отдельных `workflow_id` не вводится.

### 4. Список проектов: переименование "Init Workflow" → "Проекты"

- Роут `/workflows/init` → `/projects` (карта в
  [`front/src/app/router.tsx`](../../front/src/app/router.tsx)); пункт навигации
  [`front/src/app/app-shell.tsx:8`](../../front/src/app/app-shell.tsx#L8) — `{ to: "/projects",
  label: "Проекты" }`.
- `WorkflowList`/`WorkflowListItem`
  ([`workflow-list.tsx:14-96`](../../front/src/features/workflow/workflow-list.tsx#L14-L96))
  переименовываются в `ProjectList`/`ProjectListItem` (тот же компонент, новые данные). Каждая
  строка показывает:
  - `product_name` (раздел 3) крупным текстом, `conversation_id` — мелким/моноширинным под ним
    (fallback на короткий `conversation_id`, если проект ещё не назван);
  - список репозиториев (`conversation.repositories[].repository_name`, раздел 2) — доступен даже
    без единого run, чипами через запятую с усечением после 3-4 штук;
  - статус/шаг/дата старта **последнего** run: `active_response.response_status`/`current_step_id`/
    `created_at` — поле уже называется `active_response`, но по факту (`_active_conversation_record()`)
    это "run с максимальным `updated_at`" вне зависимости от статуса, то есть уже сегодня "последний
    run", а не обязательно "текущий активный" — переименование на бэкенде не требуется, только на
    фронте показываем это честно как `"последний запуск: {статус}, шаг {N}, {дата}"`.
  - `ConversationResponse` — новое поле `repositories: list[ConversationRepositoryResponse]`
    (`{repository_name, repository_url}`), читается напрямую из `ConversationModel.repositories`,
    доступно **независимо** от `active_response`. Новое поле `product_name: str | None`.
- Клик по строке ведёт на `/projects/{conversationId}` — новую страницу проекта (раздел 5), не на
  старый layout `InitWorkflowPage`.
- "Создать conversation"/"Продолжить последний запуск"
  ([`InitWorkflowStartPage`](../../front/src/features/workflow/init-workflow-start-page.tsx))
  переезжают на эту же страницу как "Создать проект" — сразу открывает страницу нового
  (ещё безымянного) проекта, где имя/репозитории настраиваются в левой колонке до первого запуска.
- Клиентский фильтр/поиск по `product_name`/названиям репозиториев над списком — серверная
  фильтрация/пагинация в `GET /rest/conversations/` не нужна на ожидаемом масштабе.

### 5. Страница проекта — три колонки в стиле VS Code

Заменяет сегодняшнюю `InitWorkflowPage` (`/workflows/init/:conversationId`) на
`/projects/:conversationId`, layout — грид из трёх колонок
(`grid-template-columns: minmax(220px,300px) 1fr minmax(320px,420px)`), развитие того же паттерна,
что уже применён в [`docs-page.module.css:9`](../../front/src/features/docs/docs-page.module.css#L9)
(там — две колонки).

```text
┌─────────────────────────┬────────────────────┬──────────────────────────────┐
│ Левая: файлы проекта     │ Центр: содержимое   │ Правая: управление workflow   │
│                          │ файла                │                              │
│ - название/repositories  │                      │ - селектор run проекта +      │
│   проекта (разделы 2, 3) │                      │   "Запустить новый"           │
│ - FileTree, root =       │                      │ - статус выбранного run       │
│   conversation_workspace_ │                      │   (StatusBadge/шаг/репо)      │
│   dir (arch-doc/ +        │                      │ - RequiredActionCard (диалог) │
│   runs/<workflow_id>/)    │                      │ - поток событий/лог, Timeline │
│                          │                      │ - pause/continue/retry/       │
│                          │                      │   restart                     │
│                          │                      │ - run-level репозитории       │
│                          │                      │   (тактическая правка, раздел │
│                          │                      │   2)                          │
└─────────────────────────┴────────────────────┴──────────────────────────────┘
```

**Backend — файловое дерево становится conversation-scoped**, а не response_id-scoped (в
предыдущей итерации этой спеки предполагалось `/responses/{id}/workspace/*` — заменяется на
следующее, т.к. дерево должно показывать **весь проект**, не один run):

```text
GET /conversations/{conversation_id}/workspace/tree/
GET /conversations/{conversation_id}/workspace/file/?path=...
```

Переиспользует **без изменений** уже существующий, изначально root-agnostic сервисный слой
`docs_browser.py` (`resolve_within_root`/`build_docs_tree`/`read_docs_file` уже принимают root
параметром). `_resolve_conversation_workspace_dir(conversation_id)` — аналог `_resolve_arch_repo_dir()`
([`docs.py:50-69`](../../back/app/api/rest/docs.py#L50-L69)), читает `conversation_workspace_dir` —
после раздела 1 он создаётся eagerly при создании conversation и существует всегда (404 остаётся
только для несуществующего `conversation_id`). Дерево естественным образом показывает и `arch-doc/`
(сгенерированную документацию), и `runs/<workflow_id>/` каждого прошлого/текущего run — весь проект
целиком, не нужно выбирать run, чтобы посмотреть файлы.

**Backend — список run проекта** (для селектора в правой колонке; сегодня видно только "последний"
через `active_response`, реального списка run нет):

```text
GET /conversations/{conversation_id}/responses/
```

Возвращает `list[ResponseStatusResponse]`, backed уже существующим (но не выставленным в REST)
`list_workflow_runs_for_conversation()`
([`app/db/workflow_repo.py:380`](../../back/app/db/workflow_repo.py#L380)), смёрженным с
in-memory-registry записями тем же паттерном, что уже применяет `get_conversation_async()`
(`_active_conversation_record()`/DB fallback), отсортировано по `updated_at desc`.

**Frontend:**

- Новый роут `/projects/:conversationId` (замена `/workflows/init/:conversationId` в
  [`router.tsx`](../../front/src/app/router.tsx)), новый компонент `ProjectPage`
  (замена `InitWorkflowPage`).
- Левая колонка: `ConversationRepositories` (переименованный/обобщённый `WorkflowRepositories` из
  раздела 2 — без ограничения по шагу/статусу, всегда редактируется) сверху, новый
  `ProjectWorkspaceTree` снизу — переиспользует существующий
  [`FileTree`](../../front/src/features/docs/file-tree.tsx) как есть (уже принимает дерево через
  props), новый хук `useConversationWorkspaceTree`.
- Центральная колонка: существующий
  [`FileViewer`](../../front/src/features/docs/file-viewer.tsx) как есть, путь выбранного файла — в
  `useSearchParams` (тот же паттерн, что уже в `DocsPage`).
- Правая колонка: новый `WorkflowRunPanel` — тонкая обёртка, которая (а) рендерит селектор run
  (новый хук `useConversationResponses`, дефолт — самый свежий/активный) плюс кнопку "Запустить
  новый" (форма `init_arch`, сегодняшний `InitArchForm`, без поля `repoList` — см. раздел 2;
  задизейблена/показывает причину отказа, если `WORKFLOW_TYPE_REGISTRY`-лимит уже достигнут для
  этого `conversation_id`+`workflow_type`); (б) для выбранного `response_id` рендерит **практически
  весь сегодняшний контент `InitWorkflowPage`** без изменений по сути — статус-карточку,
  `RequiredActionCard`, поток событий, `Timeline`, `TerminalResult`, кнопки
  pause/continue/retry/restart, run-level `WorkflowRepositories` — просто параметризованные
  выбранным `response_id` вместо единственного `activeResponse` из `useConversation()`.

### 6. Docs — переиспользование названия проекта

Лёгкое улучшение, не переделка модели: `DocsPage` сегодня требует вручную ввести `response_id`
([`docs-page.tsx:17-38`](../../front/src/features/docs/docs-page.tsx#L17)). Добавляем поверх
существующего поля picker — список проектов (те же данные, что и "Проекты", раздел 4, отфильтрованные
на "есть хотя бы один run"), с `product_name` вместо сырого id; выбор проекта резолвит его последний
`response_id` (тот же `active_response`, что уже вычисляется бэкендом) и подставляет в существующий
`useDocsTree(responseId)`/`useDocsFile(responseId, path)`. Сама модель Docs (response_id-scoped,
`arch_repo_dir`) не меняется — `arch_repo_dir` остаётся per-run метаданными, на conversation не
переносится (в отличие от `repositories`/`product_name`), это не входит в эту спеку.

## Что не входит в эту итерацию

- Редактирование файлов через браузер (только просмотр).
- Изменение `product_name` после создания — есть settings-эндпоинт (раздел 3), но не история
  изменений/аудит.
- Retention/автоочистка старых `run_workspace_dir`/`conversation_workspace_dir` на диске.
- Copy-on-write/переиспользование клонов между run одного проекта (см. компромисс в разделе
  "Решение") — принимается как временная деградация.
- Ограничение "один активный run на conversation" **применяется только к `init_arch`**
  (граф-workflow, единственный держатель `conversation_workspace_dir/arch-doc`). `update_arch`/`query`
  (одиночные `CliTask`, не привязанные к `conversation_workspace_dir`) продолжают запускаться
  независимо от активности `init_arch`.
- Серверная пагинация/фильтрация `GET /rest/conversations/` по `product_name` — только клиентский
  фильтр.
- Унификация `update_arch`/`query` под тот же контур `workflow_runs`/`WORKFLOW_TYPE_REGISTRY`, что и
  `init_arch` — отдельная, более крупная задача; в этой итерации `WORKFLOW_TYPE_REGISTRY` заводится
  только для `init_arch`.
- Backfill `product_name`/`repositories` для уже существующих `conversation` (созданных до этой
  миграции) — миграция добавляет колонки с дефолтом `None`/`[]`, обратной синхронизацией из истории
  run не занимаемся; для таких старых проектов название/репозитории нужно будет настроить заново.
- Перенос `arch_repo_dir` (Docs, раздел 6) на conversation — остаётся per-run метаданными.
- Одновременный просмотр нескольких run в нескольких колонках — только переключатель на один
  выбранный run за раз в правой колонке.
- Редизайн самой формы параметров `init_arch` (движок/таймаут/`analysis_scope`) — переезжает в
  правую колонку как есть, без изменений полей, кроме удаления `repoList` (раздел 2).

## Затронутые файлы (ориентировочно)

Backend:

- `app/services/init_arch_workflow.py`:
  - Новый `WORKFLOW_TYPE_REGISTRY`/`WorkflowTypeConfig` (раздел "Инвариант").
  - `create_conversation_async()` — создание `conversation_workspace_dir` на диске.
  - `create_response_async()` — общая проверка лимита инстансов через `WORKFLOW_TYPE_REGISTRY`
    (409/`WorkflowConflictError`); проверка "у conversation настроен хотя бы один репозиторий" для
    типов с `uses_conversation_repositories=True` (422/`WorkflowValidationError`); sync-forward
    `InitArchInput.product_name` → `conversation.product_name`, если там пусто.
  - `_resolve_init_arch_paths()`/`start_init_arch_workflow()` — дефолт `workspace_dir` из
    `conversation_id`, вычисление и eager-создание `run_workspace_dir` под
    `conversation_workspace_dir/runs/<workflow_id>/`; чтение `repo_list` из `conversation.repositories`
    вместо `InitArchInput.repo_list`.
  - `restart_init_arch_workflow()` — очистка только `run_workspace_dir`, не всей папки проекта.
  - `add_repository_to_workflow()`/`remove_repository_from_workflow()` (реализованы в предыдущей
    итерации) — дополнительно синхронизируют изменение в `conversation.repositories`.
  - `_workflow_response_payload()`/`get_conversation_async()` — поле `product_name` из
    `conversation.product_name` (не из `session.product_name`).
  - Новые `get_conversation_repositories_async()`/`set_conversation_repositories_async()`/
    `add_conversation_repository_async()`/`remove_conversation_repository_async()`,
    `update_conversation_product_name_async()`, `list_conversation_responses_async()` (для раздела 5),
    `build_conversation_workspace_tree_async()`/`read_conversation_workspace_file_async()`.
- `app/db/models.py` — колонки `product_name: str | None`, `repositories: JSON` на
  `ConversationModel`.
- `app/db/workflow_repo.py` — `create_conversation()`/новые `update_conversation_repositories()`,
  `update_conversation_product_name()`; `list_workflow_runs_for_conversation()` уже существует,
  переиспользуется как есть для раздела 5.
- `migrations/versions/0007_add_conversation_project_settings.py` — `product_name` + `repositories`
  на `conversations`.
- `app/api/rest/conversations.py` — `ConversationResponse.product_name`/`repositories`, новый
  `ConversationRepositoryResponse`; `CreateResponseRequest`/`InitArchInput` — `repo_list` убран из
  обязательных; `PATCH /conversations/{id}/` (`product_name`); `GET/PUT/POST
  /conversations/{id}/repositories/`, `DELETE /conversations/{id}/repositories/{repository_name}/`;
  `GET /conversations/{id}/responses/`; `GET /conversations/{id}/workspace/tree/`,
  `GET /conversations/{id}/workspace/file/`.
- `app/workflows/init_arch/nodes.py` — `_clone_repositories()` (root меняется на
  `run_workspace_dir`).
- `app/workflows/init_arch/historical.py` — `_repository_path()`.

Frontend:

- `front/src/app/router.tsx` — `/workflows/init` → `/projects`,
  `/workflows/init/:conversationId` → `/projects/:conversationId`.
- `front/src/app/app-shell.tsx` — пункт навигации "Init Workflow" → "Проекты".
- `front/src/shared/api/models.ts` — `product_name`/`repositories` на `ConversationResponse`;
  `repo_list` убран из `InitArchInput` (остаётся опциональный `product_name` для sync-forward).
- `front/src/shared/api/endpoints.ts` — `conversationsApi.getRepositories/setRepositories/
  addRepository/removeRepository/updateProductName/listResponses`; `workspaceApi.getTree/getFile`
  (conversation-scoped).
- `front/src/features/workflow/init-arch-form.tsx` — убрать редактор `repoList`; read-only превью
  репозиториев проекта.
- `front/src/features/workflow/conversation-repositories.tsx` (новый, обобщает уже существующий
  `workflow-repositories.tsx` — та же вёрстка, без ограничения по шагу/статусу run).
- `front/src/features/workflow/workflow-list.tsx` → переименовать в `project-list.tsx`
  (`ProjectList`/`ProjectListItem`) — отображение `product_name`, репозиториев из
  `conversation.repositories`, статуса/шага/даты последнего run, клиентский поиск/фильтр.
- `front/src/features/workflow/init-workflow-page.tsx` → `project-page.tsx` (`ProjectPage`) —
  трёхколоночный layout, левая (репозитории + дерево файлов), центр (`FileViewer`), правая
  (`WorkflowRunPanel` с селектором run поверх сегодняшнего содержимого `InitWorkflowPage`).
- `front/src/features/workflow/project-workspace-tree.tsx` (новый, реиспользует `FileTree`/
  `FileViewer` из `features/docs/`) + `hooks.ts` (`useConversationWorkspaceTree`,
  `useConversationWorkspaceFile`, `useConversationResponses`).
- `front/src/features/docs/docs-page.tsx` — опциональный project-picker поверх ручного ввода
  `response_id`.

Инфраструктура:

- Права на диске не меняются — `/workspace` уже `chown appuser:appuser` целиком на уровне volume
  (`Dockerfile:29`), поддиректории создаются процессом `appuser` и так уже сегодня.
