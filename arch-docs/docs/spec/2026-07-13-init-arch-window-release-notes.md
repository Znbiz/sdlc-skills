# Release notes для каждого исторического окна init_arch — план внедрения

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ SUB-SKILL: используй superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans для выполнения плана задача за задачей. Шаги отмечаются чекбоксами (`- [ ]`).

**Цель:** После каждой итерации (исторического окна) workflow `init_arch` автоматически формировать единый release notes файл по всему продукту — аналог `update-repo-arch-skill/assets/release-note-template.md`, но построенный из данных, уже накопленных в `WorkflowSessionRecord` за это окно (diff по каждому репозиторию, изменённые артефакты, открытые вопросы), без раздела «Каскадные эффекты» (в `init_arch` нет signal_routing-механики между репозиториями).

**Архитектура:** Новый шаг графа `StepId.GENERATE_RELEASE_NOTES` между `VALIDATE_FINAL` и `CONFIRM_NEXT_TEMPORAL_WINDOW`. Узел `node_generate_release_notes` (по образцу `node_refine_features`) прогоняет LLM-воркера с новым reference-чеклистом и структурированным контекстом окна (собранным в `prompts.py`), затем регистрирует созданный файл через `KnowledgeArtifactService.collect_worker_artifacts`. Файл пишется в `release-notes/window-<window_index>-<snapshot_date>.md`. Чтобы секция «Что изменилось» была точной на втором и последующих окнах (а не повторяла список артефактов за весь прогон), в `ArtifactRecord` добавляется поле `last_updated_window_index`, проставляемое сервисом при регистрации артефакта.

**Tech Stack:** Python 3.14, LangGraph (`StateGraph`), Pydantic v2, pytest/pytest-asyncio — тот же стек, что и у остального `app/workflows/init_arch`.

## Глобальные ограничения

- Код и идентификаторы на английском; русский — только для docstring/комментариев там, где это действительно нужно (гайдлайны pylines этого репозитория).
- Новая/изменённая логика должна поставляться с тестами, покрывающими дельту на уровне, близком к 100%.
- Не переписывать существующие узлы графа сверх необходимого — `node_validate_final` меняет только целевой шаг (`next_step`), остальная реализация (`_simple_llm_step`) переиспользуется как есть.
- Не создавать отдельный markdown-шаблон `assets/release-notes-template.md`: LLM-воркер не имеет доступа к `shared_assets/` (это уже установленный факт в этом сервисе, см. `arch-docs/docs/spec/2026-07-13-architecture-artifact-lint.md`, раздел «Предварительные правки»). Структура release notes инлайнится текстом прямо в reference-чеклист, как это уже сделано для `features/*.md` в `checklist-features-and-index.md`.
- Файл release notes не bootstrap-скаффолдится (в отличие от `architecture/hld.md` и т.п.) — его имя зависит от `window_index`/`snapshot_date`, неизвестных заранее; воркер пишет его с нуля, как `features/<name>.md`.
- Вне скоупа: раздел «Каскадные эффекты» из `update-repo-arch-skill`-шаблона не переносится — в `init_arch` нет данных для его заполнения.

---

## Структура файлов

- **Изменить:** `arch-docs/app/workflows/init_arch/domain/models.py` — добавить `StepId.GENERATE_RELEASE_NOTES` и `ArtifactRecord.last_updated_window_index`.
- **Изменить:** `arch-docs/app/workflows/init_arch/domain/steps.py` — вставить `StepDefinition` для нового шага, поправить `required_previous_steps` у `CONFIRM_NEXT_TEMPORAL_WINDOW`.
- **Изменить:** `arch-docs/app/workflows/init_arch/graph.py` — зарегистрировать новый узел в `_NODE_FUNCTIONS`.
- **Изменить:** `arch-docs/app/workflows/init_arch/knowledge.py` — bootstrap каталога `release-notes/`, новый `artifact_kind`, проставление `last_updated_window_index` в `_register_artifacts`.
- **Изменить:** `arch-docs/app/workflows/init_arch/prompts.py` — новый context-блок для окна + запись в `STEP_TO_REFERENCE`.
- **Создать:** `arch-docs/app/workflows/shared_assets/init_arch/references/checklist-release-notes.md` — инлайновая структура release notes для воркера.
- **Изменить:** `arch-docs/app/workflows/init_arch/nodes.py` — новый `node_generate_release_notes`, ретаргет `node_validate_final`.
- **Изменить:** `arch-docs/docs/workflows/init.md` и `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md` — обновить списки шагов.
- **Изменить:** `arch-docs/tests/workflows/init_arch/domain/test_models.py`, новый `test_steps.py`, `test_graph.py`, `test_knowledge.py`, `test_prompts.py`, `test_nodes.py`.

---

### Задача 1: Добавить `StepId.GENERATE_RELEASE_NOTES` и `ArtifactRecord.last_updated_window_index`

- [x] Выполнено
- Мини-отчёт: в `domain/models.py` добавлены `StepId.GENERATE_RELEASE_NOTES` и `ArtifactRecord.last_updated_window_index`, тесты `test_models.py` расширены и зелёные.

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/domain/models.py:10-26` (StepId), `arch-docs/app/workflows/init_arch/domain/models.py:151-155` (ArtifactRecord)
- Тест: `arch-docs/tests/workflows/init_arch/domain/test_models.py`

**Интерфейсы:**
- Производит: `StepId.GENERATE_RELEASE_NOTES` (значение `"generate_release_notes"`), `ArtifactRecord.last_updated_window_index: int = 0` — используются в задачах 2, 3, 6.

- [ ] **Шаг 1: Написать падающий тест на новое значение StepId и поле ArtifactRecord**

В `arch-docs/tests/workflows/init_arch/domain/test_models.py` добавить:

```python
def test_step_id_has_generate_release_notes_value() -> None:
    assert StepId.GENERATE_RELEASE_NOTES.value == "generate_release_notes"


def test_artifact_record_defaults_last_updated_window_index_to_zero() -> None:
    artifact = ArtifactRecord(artifact_path="release-notes/window-0-2020-01-01.md", artifact_kind="release_notes")
    assert artifact.last_updated_window_index == 0


def test_artifact_record_accepts_explicit_window_index() -> None:
    artifact = ArtifactRecord(
        artifact_path="release-notes/window-2-2020-07-01.md",
        artifact_kind="release_notes",
        last_updated_window_index=2,
    )
    assert artifact.last_updated_window_index == 2
```

Убедиться, что `StepId` и `ArtifactRecord` уже импортированы в начале файла (проверить существующий блок `from app.workflows.init_arch.domain.models import (...)` или аналогичный импорт из `app.workflows.init_arch.domain`); если `ArtifactRecord` ещё не импортирован — добавить его в существующий импорт.

- [ ] **Шаг 2: Убедиться, что тест падает**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/domain/test_models.py -k "generate_release_notes or last_updated_window_index" -v`
Expected: FAIL — `AttributeError: GENERATE_RELEASE_NOTES` и `TypeError: unexpected keyword argument 'last_updated_window_index'`.

- [ ] **Шаг 3: Добавить StepId.GENERATE_RELEASE_NOTES**

В `arch-docs/app/workflows/init_arch/domain/models.py:23-24` вставить новое значение между `VALIDATE_FINAL` и `CONFIRM_NEXT_TEMPORAL_WINDOW`:

```python
    VALIDATE_FINAL = "validate_final"
    GENERATE_RELEASE_NOTES = "generate_release_notes"
    CONFIRM_NEXT_TEMPORAL_WINDOW = "confirm_next_temporal_window"
```

- [ ] **Шаг 4: Добавить поле в ArtifactRecord**

В `arch-docs/app/workflows/init_arch/domain/models.py:151-155`:

```python
class ArtifactRecord(pydantic.BaseModel):
    artifact_path: str
    artifact_kind: str
    source_refs: list[str] = pydantic.Field(default_factory=list)
    last_updated_step: StepId | None = None
    last_updated_window_index: int = 0
```

- [ ] **Шаг 5: Прогнать тесты**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/domain/test_models.py -v`
Expected: PASS, все тесты файла зелёные.

- [ ] **Шаг 6: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/domain/models.py arch-docs/tests/workflows/init_arch/domain/test_models.py
git commit -m "feat(arch-docs): добавить шаг generate_release_notes и window-индекс артефакта"
```

---

### Задача 2: Вставить StepDefinition в STEP_DEFINITIONS

- [x] Выполнено
- Мини-отчёт: шаг `generate_release_notes` встроен между `validate_final` и `confirm_next_temporal_window`, добавлен новый `test_steps.py`, переходные зависимости подтверждены тестами.

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/domain/steps.py:82-94`
- Создать: `arch-docs/tests/workflows/init_arch/domain/test_steps.py`

**Интерфейсы:**
- Потребляет: `StepId.GENERATE_RELEASE_NOTES` (Задача 1).
- Производит: `STEP_DEFINITION_BY_ID[StepId.GENERATE_RELEASE_NOTES]` с `required_previous_steps=[StepId.VALIDATE_FINAL]`, `uses_llm_worker=True` — используется графом (Задача 3) и `advance_step()` (Задача 6).

- [ ] **Шаг 1: Написать падающий тест**

Создать `arch-docs/tests/workflows/init_arch/domain/test_steps.py`:

```python
from app.workflows.init_arch.domain import STEP_DEFINITION_BY_ID, STEP_DEFINITIONS, StepId


def test_generate_release_notes_is_between_validate_final_and_confirm_window() -> None:
    step_ids = [definition.step_id for definition in STEP_DEFINITIONS]
    validate_final_index = step_ids.index(StepId.VALIDATE_FINAL)
    generate_notes_index = step_ids.index(StepId.GENERATE_RELEASE_NOTES)
    confirm_window_index = step_ids.index(StepId.CONFIRM_NEXT_TEMPORAL_WINDOW)
    assert validate_final_index < generate_notes_index < confirm_window_index


def test_generate_release_notes_requires_validate_final_and_uses_llm() -> None:
    definition = STEP_DEFINITION_BY_ID[StepId.GENERATE_RELEASE_NOTES]
    assert definition.required_previous_steps == [StepId.VALIDATE_FINAL]
    assert definition.uses_llm_worker is True
    assert definition.requires_historical_prep is False


def test_confirm_next_temporal_window_now_requires_generate_release_notes() -> None:
    definition = STEP_DEFINITION_BY_ID[StepId.CONFIRM_NEXT_TEMPORAL_WINDOW]
    assert definition.required_previous_steps == [StepId.GENERATE_RELEASE_NOTES]
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/domain/test_steps.py -v`
Expected: FAIL — `KeyError: StepId.GENERATE_RELEASE_NOTES` (нет в `STEP_DEFINITION_BY_ID`), и `required_previous_steps == [StepId.VALIDATE_FINAL]` для `CONFIRM_NEXT_TEMPORAL_WINDOW` не совпадёт с текущим значением.

- [ ] **Шаг 3: Вставить StepDefinition**

В `arch-docs/app/workflows/init_arch/domain/steps.py:82-94` заменить:

```python
    StepDefinition(
        step_id=StepId.VALIDATE_FINAL,
        title="Validate final output",
        required_previous_steps=[StepId.RUN_KNOWLEDGE_LINT],
        uses_llm_worker=False,
    ),
    StepDefinition(
        step_id=StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
        title="Confirm next temporal window",
        required_previous_steps=[StepId.VALIDATE_FINAL],
        uses_llm_worker=False,
        allows_user_pause=True,
    ),
```

на:

```python
    StepDefinition(
        step_id=StepId.VALIDATE_FINAL,
        title="Validate final output",
        required_previous_steps=[StepId.RUN_KNOWLEDGE_LINT],
        uses_llm_worker=False,
    ),
    StepDefinition(
        step_id=StepId.GENERATE_RELEASE_NOTES,
        title="Generate release notes",
        required_previous_steps=[StepId.VALIDATE_FINAL],
    ),
    StepDefinition(
        step_id=StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
        title="Confirm next temporal window",
        required_previous_steps=[StepId.GENERATE_RELEASE_NOTES],
        uses_llm_worker=False,
        allows_user_pause=True,
    ),
```

(`uses_llm_worker` для `GENERATE_RELEASE_NOTES` не указан явно — используется дефолт `True` из `StepDefinition`, так же как у `REFINE_FEATURES`.)

- [ ] **Шаг 4: Прогнать тесты**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/domain/test_steps.py -v`
Expected: PASS.

- [ ] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/domain/steps.py arch-docs/tests/workflows/init_arch/domain/test_steps.py
git commit -m "feat(arch-docs): вставить шаг generate_release_notes в последовательность STEP_DEFINITIONS"
```

---

### Задача 3: Зарегистрировать узел в графе

- [x] Выполнено
- Мини-отчёт: `graph.py` импортирует и регистрирует `node_generate_release_notes`, маршрут после `validate_final` теперь ведёт в новый шаг, `test_graph.py` подтверждает новый линейный переход.

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/graph.py:8-25` (импорт), `arch-docs/app/workflows/init_arch/graph.py:33-49` (`_NODE_FUNCTIONS`)
- Изменить: `arch-docs/tests/workflows/init_arch/test_graph.py`

**Интерфейсы:**
- Потребляет: `node_generate_release_notes` из `nodes.py` (реализуется в Задаче 6 — на момент этой задачи функция ещё не существует, поэтому Задачу 3 нельзя протестировать полностью до Задачи 6; см. шаг 0 ниже).
- Производит: узел `"generate_release_notes"` в `build_graph()`, автоматически встроенный в линейный маршрут между `validate_final` и `confirm_next_temporal_window` (стандартный `_route_after_node`, кастомная маршрутизация не нужна).

- [ ] **Шаг 0: Добавить временную заглушку узла (будет заменена в Задаче 6)**

Чтобы граф собирался до реализации самого узла, в `arch-docs/app/workflows/init_arch/nodes.py` после `node_validate_final` (строка 585) добавить временную заглушку:

```python
async def node_generate_release_notes(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.generate_release_notes")
    return await _simple_llm_step(state, StepId.GENERATE_RELEASE_NOTES, StepId.CONFIRM_NEXT_TEMPORAL_WINDOW)
```

(Это не заглушка в смысле фейкового кода — `_simple_llm_step` уже полностью рабочая реализация, которую используют `node_prepare_temp_workspace`, `node_clone_repositories`, `node_assess_scope_and_domains`. Задача 6 заменит эту реализацию на версию с регистрацией артефактов через `collect_worker_artifacts`, т.к. release notes — файл, который должен попасть в `session.artifacts`.)

- [ ] **Шаг 1: Написать падающий тест**

В `arch-docs/tests/workflows/init_arch/test_graph.py:44-62` (`test_build_graph_has_all_nodes`) добавить `"generate_release_notes"` в список `expected_nodes` между `"validate_final"` и `"confirm_next_temporal_window"`:

```python
    expected_nodes = [
        "define_scope",
        "request_repository_list",
        "prepare_temp_workspace",
        "clone_repositories",
        "refresh_main_branches",
        "plan_repository_order",
        "assess_scope_and_domains",
        "analyze_repositories",
        "interview_user",
        "refine_features",
        "build_navigation_index",
        "run_knowledge_lint",
        "validate_final",
        "generate_release_notes",
        "confirm_next_temporal_window",
        "finalize_progress",
        "handle_error",
    ]
```

Заменить тест `test_route_after_validate_final_goes_to_confirm_next_temporal_window` (строки 102-105) на:

```python
def test_route_after_validate_final_goes_to_generate_release_notes():
    route = _route_after_node("validate_final")
    state = _make_state(step_error=None)
    assert route(state) == "generate_release_notes"


def test_route_after_generate_release_notes_goes_to_confirm_next_temporal_window():
    route = _route_after_node("generate_release_notes")
    state = _make_state(step_error=None)
    assert route(state) == "confirm_next_temporal_window"
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/test_graph.py -v`
Expected: FAIL — `"generate_release_notes"` отсутствует среди `graph.nodes.keys()`, `_route_after_node("validate_final")` всё ещё возвращает `"confirm_next_temporal_window"`.

- [ ] **Шаг 3: Зарегистрировать узел в графе**

В `arch-docs/app/workflows/init_arch/graph.py:8-25` добавить импорт `node_generate_release_notes` в список импортов из `nodes` (по алфавиту, между `node_finalize_progress` и `node_handle_error`... фактически между `node_define_scope` и `node_finalize_progress` — сохранить алфавитный порядок существующего блока):

```python
from app.workflows.init_arch.nodes import (
    node_analyze_repositories,
    node_assess_scope_and_domains,
    node_build_navigation_index,
    node_clone_repositories,
    node_confirm_next_temporal_window,
    node_define_scope,
    node_finalize_progress,
    node_generate_release_notes,
    node_handle_error,
    node_interview_user,
    node_plan_repository_order,
    node_prepare_temp_workspace,
    node_refine_features,
    node_refresh_main_branches,
    node_request_repository_list,
    node_run_knowledge_lint,
    node_validate_final,
)
```

В `arch-docs/app/workflows/init_arch/graph.py:33-49` (`_NODE_FUNCTIONS`) добавить строку между `StepId.VALIDATE_FINAL` и `StepId.CONFIRM_NEXT_TEMPORAL_WINDOW`:

```python
    StepId.VALIDATE_FINAL: node_validate_final,
    StepId.GENERATE_RELEASE_NOTES: node_generate_release_notes,
    StepId.CONFIRM_NEXT_TEMPORAL_WINDOW: node_confirm_next_temporal_window,
```

Ничего больше в `graph.py` менять не нужно: `_LINEAR_STEP_IDS`/`_LINEAR_NODES` строятся из `STEP_DEFINITIONS` (Задача 2) и `_NODE_FUNCTIONS` автоматически, а `_route_after_node` — общий роутер, кастомная маршрутизация нужна только для `confirm_next_temporal_window`.

- [ ] **Шаг 4: Прогнать тесты**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/test_graph.py -v`
Expected: PASS.

- [ ] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/graph.py arch-docs/app/workflows/init_arch/nodes.py arch-docs/tests/workflows/init_arch/test_graph.py
git commit -m "feat(arch-docs): встроить generate_release_notes в граф init_arch"
```

---

### Задача 4: knowledge.py — каталог, artifact_kind, window-индекс

- [x] Выполнено
- Мини-отчёт: bootstrap теперь создаёт `release-notes/`, `KnowledgeArtifactService` распознаёт `release_notes` и проставляет `last_updated_window_index` при регистрации артефактов.

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/knowledge.py:36-53` (`_DIRECTORY_PATHS`, `_ARTIFACT_KINDS`), `arch-docs/app/workflows/init_arch/knowledge.py:272-310` (`_register_artifacts`, `_artifact_kind_from_path`)
- Изменить: `arch-docs/tests/workflows/init_arch/test_knowledge.py`

**Интерфейсы:**
- Потребляет: `ArtifactRecord.last_updated_window_index` (Задача 1).
- Производит: каталог `release-notes/` создаётся при `bootstrap_arch_repo`; `_artifact_kind_from_path("release-notes/window-0-2020-01-01.md") == "release_notes"`; `_register_artifacts(...)` проставляет `last_updated_window_index = session.historical_analysis.window_index` для каждого зарегистрированного артефакта.

- [ ] **Шаг 1: Написать падающие тесты**

В `arch-docs/tests/workflows/init_arch/test_knowledge.py` добавить (используя существующий `_make_session()` из строк 13-18):

```python
@pytest.mark.asyncio
async def test_bootstrap_arch_repo_creates_release_notes_directory(tmp_path: Path) -> None:
    asset_loader = WorkflowAssetLoader(
        Path("/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/app/workflows/shared_assets")
    )
    service = KnowledgeArtifactService(asset_loader=asset_loader)

    await service.bootstrap_arch_repo(_make_session(), arch_repo_dir=str(tmp_path / "arch-repo"))

    assert (tmp_path / "arch-repo" / "release-notes").is_dir()


def test_artifact_kind_from_path_recognizes_release_notes() -> None:
    assert KnowledgeArtifactService._artifact_kind_from_path("release-notes/window-0-2020-01-01.md") == "release_notes"


@pytest.mark.asyncio
async def test_collect_worker_artifacts_stamps_current_window_index() -> None:
    service = KnowledgeArtifactService()
    session = _make_session().model_copy(
        update={"historical_analysis": _make_session().historical_analysis.model_copy(update={"window_index": 2})}
    )

    result = await service.collect_worker_artifacts(
        session,
        step_id=StepId.GENERATE_RELEASE_NOTES,
        created_artifacts=["release-notes/window-2-2020-07-01.md"],
    )

    artifact = next(
        item for item in result.session.artifacts if item.artifact_path == "release-notes/window-2-2020-07-01.md"
    )
    assert artifact.last_updated_window_index == 2
    assert artifact.artifact_kind == "release_notes"
```

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/test_knowledge.py -k "release_notes or window_index" -v`
Expected: FAIL — каталог `release-notes/` не создаётся, `_artifact_kind_from_path` возвращает `"knowledge_artifact"`, `last_updated_window_index` остаётся `0` по дефолту, а не `2`.

- [ ] **Шаг 3: Добавить каталог в bootstrap**

В `arch-docs/app/workflows/init_arch/knowledge.py:36-45` (`_DIRECTORY_PATHS`):

```python
_DIRECTORY_PATHS: Final[tuple[str, ...]] = (
    "features",
    "architecture",
    "architecture/integrations",
    "architecture/contracts",
    "architecture/storage",
    "architecture/structure",
    "release-notes",
    "wiki",
    "wiki/maps",
)
```

- [ ] **Шаг 4: Добавить artifact_kind для release-notes**

В `arch-docs/app/workflows/init_arch/knowledge.py:301-310` (`_artifact_kind_from_path`):

```python
    @staticmethod
    def _artifact_kind_from_path(artifact_path: str) -> str:
        path = pathlib.PurePosixPath(artifact_path)
        if path.parts[:1] == ("features",):
            return "feature"
        if path.parts[:1] == ("architecture",):
            return "architecture_artifact"
        if path.parts[:1] == ("release-notes",):
            return "release_notes"
        if path.parts[:1] == ("wiki",):
            return "navigation_artifact"
        return "knowledge_artifact"
```

- [ ] **Шаг 5: Проставлять window_index при регистрации артефакта**

В `arch-docs/app/workflows/init_arch/knowledge.py:272-299` (`_register_artifacts`) добавить `last_updated_window_index` в конструктор `ArtifactRecord`:

```python
    def _register_artifacts(
        self,
        session: WorkflowSessionRecord,
        *,
        written_artifacts: list[str],
        step_id: StepId,
        source_refs: list[str],
    ) -> WorkflowSessionRecord:
        updated_session = session
        today = dt.datetime.now(dt.UTC).date().isoformat()
        for artifact_path in written_artifacts:
            artifact = ArtifactRecord(
                artifact_path=artifact_path,
                artifact_kind=_ARTIFACT_KINDS.get(artifact_path, self._artifact_kind_from_path(artifact_path)),
                source_refs=[*source_refs, today],
                last_updated_step=step_id,
                last_updated_window_index=session.historical_analysis.window_index,
            )
            updated_session = register_artifact(updated_session, artifact=artifact)
            self._audit_service.record(
                WorkflowEventRecord(
                    event_type=EventType.ARTIFACT_WRITTEN,
                    actor=AuditActor.SERVICE,
                    session_id=updated_session.session_id,
                    step_id=step_id,
                    payload={"artifact_path": artifact_path, "artifact_kind": artifact.artifact_kind},
                )
            )
        return updated_session
```

(`register_artifact()` в `domain/operations.py` уже заменяет старую запись новой по `artifact_path` — значит `last_updated_window_index` у каждого артефакта всегда отражает окно его *последнего* изменения, что и нужно секции «Что изменилось» в Задаче 5/7: артефакты с `last_updated_window_index == session.historical_analysis.window_index` — это то, что реально поменялось в текущем окне.)

- [ ] **Шаг 6: Прогнать тесты**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/test_knowledge.py -v`
Expected: PASS, все тесты файла зелёные (включая уже существующие — регрессия не допускается).

- [ ] **Шаг 7: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/knowledge.py arch-docs/tests/workflows/init_arch/test_knowledge.py
git commit -m "feat(arch-docs): bootstrap release-notes/ и window-индекс в KnowledgeArtifactService"
```

---

### Задача 5: Reference-чеклист для release notes

- [x] Выполнено
- Мини-отчёт: создан `references/checklist-release-notes.md`, загрузка через `WorkflowAssetLoader` проверена отдельной командой `uv run python -c ...` и проходит успешно.

**Файлы:**
- Создать: `arch-docs/app/workflows/shared_assets/init_arch/references/checklist-release-notes.md`

**Интерфейсы:**
- Потребляется: `prompts.py` через `STEP_TO_REFERENCE["generate_release_notes"]` (Задача 6).

- [ ] **Шаг 1: Создать файл**

Создать `arch-docs/app/workflows/shared_assets/init_arch/references/checklist-release-notes.md`:

````markdown
# Шаг workflow: generate_release_notes

Сформировать один release notes файл по всему продукту, закрывающий текущее историческое окно (temporal window) — все репозитории, а не один. Это единственный отчётный документ окна: он не заменяет `features/*.md`/`architecture/*.md`, а только суммирует, что в них изменилось за это окно.

## Куда писать

`release-notes/window-<window_index>-<snapshot_date>.md`, где `window_index` и `snapshot_date` — значения `Window index` и `Current snapshot` из блока «Контекст release notes для текущего окна» в этом промпте (бери их оттуда буквально, не пересчитывай). Пример: `release-notes/window-3-2020-01-01.md`.

## Структура файла

```markdown
# Release notes — окно <window_index> (<previous_snapshot> → <current_snapshot>)

**Продукт:** <product_name>

## Что изменилось

Пройтись по списку «Артефакты, изменённые в этом окне» из контекста и перечислить каждый как markdown-ссылку на сам файл (относительный путь от `release-notes/`, т.е. с `../` перед путём) с коротким описанием, что в нём изменилось — опираясь на diff-данные соответствующего репозитория и на сам изменённый артефакт.

- [../architecture/integrations/<service>.md](../architecture/integrations/<service>.md) — <короткое описание>

Если список артефактов этого окна пуст — написать явно: "За это окно ни один knowledge-артефакт не был изменён" (не пропускать секцию).

## Затронутые репозитории

Таблица по каждому репозиторию из блока «Репозитории в этом окне», у которого `Commit range status` не `no_changes`:

| Репозиторий | Diff severity | Commit range | Краткое summary изменений |
|---|---|---|---|

Столбец "Diff severity" — значение `Diff severity` из контекста (`full_required`/`local`/`broad`/`no_signal`). Столбец "Краткое summary" — 1-2 предложения на основе `Diff stat summary`/`Commit log summary` этого репозитория.

## Репозитории без изменений

Таблица по репозиториям, у которых `Commit range status = no_changes`:

| Репозиторий | Commit range |
|---|---|

Если таких нет — написать "В этом окне у всех репозиториев были изменения".

## Репозитории с невалидным baseline

Таблица по репозиториям, у которых `Commit range status = invalid_range` (история переписана — force-push/rebase):

| Репозиторий | Причина |
|---|---|

Причину бери из `Заметка` соответствующего репозитория в контексте. Если таких репозиториев нет — не создавай пустую таблицу, напиши "Невалидных baseline в этом окне не обнаружено".

## Открытые вопросы

Перечислить вопросы из блока «Открытые вопросы» контекста (статус `open` на момент завершения этого окна) как есть — ID и текст вопроса. Если список пуст — "Открытых вопросов после этого окна не осталось".

## Следующий шаг

Одно-два предложения: это окно `window_index=<N>` закрыто, следующий шаг графа — `confirm_next_temporal_window`, который либо предложит пользователю продолжить на следующее окно, либо (если это было последнее окно) перейдёт к `finalize_progress`. Если в разделе «Репозитории с невалидным baseline» выше есть записи — явно порекомендовать проверить их в первую очередь на следующем окне.
```

## Не делать

- Не добавляй раздел «Каскадные эффекты» — в `init_arch` нет данных о влиянии изменений одного репозитория на другой (в отличие от `update-repo-arch-skill`), придумывать их нельзя.
- Не переписывай и не дублируй содержимое `features/*.md`/`architecture/*.md` внутри release notes — только ссылки и краткие описания.
- Не используй данные, которых нет в блоке «Контекст release notes для текущего окна» этого промпта — не открывай заново git log/diff, эти данные уже собраны сервисом за это окно.
````

- [ ] **Шаг 2: Проверить, что файл читается загрузчиком ассетов**

Run:

```bash
cd arch-docs && uv run python -c "
from app.workflows.shared_assets import get_workflow_asset_loader
content = get_workflow_asset_loader().read_text('init_arch', 'references/checklist-release-notes.md')
assert 'window_index' in content
assert 'Каскадные эффекты' not in content
print('OK')
"
```

Expected: печатает `OK` без исключений.

- [ ] **Шаг 3: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/shared_assets/init_arch/references/checklist-release-notes.md
git commit -m "docs(arch-docs): добавить reference-чеклист generate_release_notes"
```

---

### Задача 6: prompts.py — контекст окна для воркера

- [x] Выполнено
- Мини-отчёт: `build_step_prompt()` получил блок `Контекст release notes для текущего окна`, `STEP_TO_REFERENCE` знает новый шаг, тесты `test_prompts.py` покрывают список репозиториев, артефактов и fallback для других шагов.

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/prompts.py:1-30` (импорты, `STEP_TO_REFERENCE`), `arch-docs/app/workflows/init_arch/prompts.py:137-218` (`build_step_prompt`)
- Изменить: `arch-docs/tests/workflows/init_arch/test_prompts.py`

**Интерфейсы:**
- Потребляет: `classify_diff_severity` (уже существует в `domain.signal_routing`), `HistoricalAnalysisState`, `ArtifactRecord.last_updated_window_index` (Задача 1).
- Производит: `build_step_prompt("generate_release_notes", state)` включает блок `# Контекст release notes для текущего окна` со всеми репозиториями окна, изменёнными артефактами и открытыми вопросами; для остальных шагов этот блок неизменно равен `"(не применимо для этого шага)"`.

- [ ] **Шаг 1: Написать падающие тесты**

В `arch-docs/tests/workflows/init_arch/test_prompts.py` добавить (используя существующий `_make_state()` helper строк 11-32):

```python
def test_build_step_prompt_release_notes_block_not_applicable_for_other_steps():
    with patch.object(prompts_module, "_load_skill_md", return_value="SKILL"):
        result = build_step_prompt("define_scope", _make_state())
    assert "(не применимо для этого шага)" in result


def test_build_step_prompt_release_notes_includes_all_repositories(tmp_path):
    ref_file = tmp_path / "init_arch" / "references" / "checklist-release-notes.md"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("RELEASE NOTES REFERENCE")
    skill_file = tmp_path / "init_arch" / "SKILL.md"
    skill_file.write_text("SKILL")

    repo_a = RepositoryExecution(
        repository_name="svc-a",
        commit_range="a1..a2",
        commit_range_status=CommitRangeStatus.DIFF_COLLECTED,
        diff_stat_summary="3 files changed",
        commit_log_summary="a2 fix bug",
    )
    repo_b = RepositoryExecution(
        repository_name="svc-b",
        commit_range_status=CommitRangeStatus.NO_CHANGES,
    )
    state = _make_state()
    state["session"] = state["session"].model_copy(
        update={
            "repositories": [repo_a, repo_b],
            "historical_analysis": state["session"].historical_analysis.model_copy(
                update={"window_index": 1, "current_snapshot_at": dt.date(2020, 7, 1)}
            ),
        }
    )

    with (
        patch.object(
            prompts_module,
            "get_workflow_asset_loader",
            return_value=WorkflowAssetLoader(tmp_path),
            create=True,
        ),
    ):
        result = build_step_prompt("generate_release_notes", state)

    assert "RELEASE NOTES REFERENCE" in result
    assert "Window index: 1" in result
    assert "svc-a" in result
    assert "svc-b" in result
    assert "a1..a2" in result
    assert "no_changes" in result


def test_build_step_prompt_release_notes_lists_artifacts_changed_this_window(tmp_path):
    ref_file = tmp_path / "init_arch" / "references" / "checklist-release-notes.md"
    ref_file.parent.mkdir(parents=True)
    ref_file.write_text("REF")
    skill_file = tmp_path / "init_arch" / "SKILL.md"
    skill_file.write_text("SKILL")

    state = _make_state()
    state["session"] = state["session"].model_copy(
        update={
            "historical_analysis": state["session"].historical_analysis.model_copy(update={"window_index": 1}),
            "artifacts": [
                ArtifactRecord(
                    artifact_path="architecture/hld.md",
                    artifact_kind="architecture_artifact",
                    last_updated_window_index=1,
                ),
                ArtifactRecord(
                    artifact_path="glossary.md",
                    artifact_kind="glossary",
                    last_updated_window_index=0,
                ),
            ],
        }
    )

    with patch.object(
        prompts_module, "get_workflow_asset_loader", return_value=WorkflowAssetLoader(tmp_path), create=True
    ):
        result = build_step_prompt("generate_release_notes", state)

    assert "architecture/hld.md" in result
    assert "glossary.md" not in result
```

Добавить `ArtifactRecord` в импорт из `app.workflows.init_arch.domain` в начале `test_prompts.py` (строка 5).

- [ ] **Шаг 2: Убедиться, что тесты падают**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/test_prompts.py -k "release_notes" -v`
Expected: FAIL — блок `# Контекст release notes для текущего окна` ещё не существует, `STEP_TO_REFERENCE` не содержит `"generate_release_notes"`.

- [ ] **Шаг 3: Добавить импорт classify_diff_severity и запись в STEP_TO_REFERENCE**

В `arch-docs/app/workflows/init_arch/prompts.py:5`:

```python
from app.workflows.init_arch.domain import CommitRangeStatus, RepositoryExecution, StepId, classify_diff_severity
```

В `arch-docs/app/workflows/init_arch/prompts.py:15-30` (`STEP_TO_REFERENCE`), добавить строку между `"validate_final"` и `"finalize_progress"`:

```python
STEP_TO_REFERENCE: typing.Final[dict[str, str]] = {
    "define_scope": "",
    "request_repository_list": "",
    "prepare_temp_workspace": "",
    "clone_repositories": "",
    "refresh_main_branches": "",
    "plan_repository_order": "",
    "assess_scope_and_domains": "references/checklist-scope-and-domain-assessment.md",
    "analyze_repositories": "",
    "interview_user": "references/checklist-glossary-and-open-questions.md",
    "refine_features": "references/checklist-features-and-index.md",
    "build_navigation_index": "references/knowledge-workflow.md",
    "run_knowledge_lint": "references/knowledge-workflow.md",
    "validate_final": "references/checklist-repository-consistency-review.md",
    "generate_release_notes": "references/checklist-release-notes.md",
    "finalize_progress": "",
}
```

- [ ] **Шаг 4: Добавить сборщик контекста окна**

В `arch-docs/app/workflows/init_arch/prompts.py` после `_build_temporal_delta_block` (после строки 134, перед `def build_step_prompt`) добавить:

```python
_RELEASE_NOTES_STEP_VALUE: typing.Final[str] = "generate_release_notes"
_NOT_APPLICABLE_RELEASE_NOTES_BLOCK: typing.Final[str] = "(не применимо для этого шага)"


def _build_release_notes_context_block(state: InitArchState) -> str:
    session = state["session"]
    historical = session.historical_analysis

    lines = [
        f"Window index: {historical.window_index}",
        f"Previous snapshot: {historical.previous_snapshot_at or '—'}",
        f"Current snapshot: {historical.current_snapshot_at or '—'}",
        "",
        "Репозитории в этом окне:",
    ]
    for repository in session.repositories:
        lines.extend(
            [
                "",
                f"### {repository.repository_name}",
                f"Commit range: {repository.commit_range or '—'}",
                f"Commit range status: {repository.commit_range_status.value}",
                f"Diff severity: {classify_diff_severity(repository).value}",
                "Diff stat summary:",
                repository.diff_stat_summary or "нет",
                "Commit log summary:",
                repository.commit_log_summary or "нет",
                "Изменённые пути:",
                _format_path_list(repository.changed_paths, expanded=False),
            ]
        )
        if repository.temporal_delta_note:
            lines.append(f"Заметка: {repository.temporal_delta_note}")

    artifacts_this_window = [
        artifact
        for artifact in session.artifacts
        if artifact.last_updated_window_index == historical.window_index
    ]
    lines.extend(["", "Артефакты, изменённые в этом окне:"])
    if artifacts_this_window:
        lines.extend(f"- {artifact.artifact_path} ({artifact.artifact_kind})" for artifact in artifacts_this_window)
    else:
        lines.append("нет")

    open_questions = [question for question in session.open_questions if question.status == "open"]
    lines.extend(["", "Открытые вопросы:"])
    if open_questions:
        lines.extend(f"- {question.question_id}: {question.question_text}" for question in open_questions)
    else:
        lines.append("нет")

    return "\n".join(lines)
```

- [ ] **Шаг 5: Подключить блок в build_step_prompt**

В `arch-docs/app/workflows/init_arch/prompts.py:137-218` (`build_step_prompt`), после вычисления `temporal_delta_block` (после строки 154) добавить:

```python
    release_notes_block = (
        _build_release_notes_context_block(state)
        if step_value == _RELEASE_NOTES_STEP_VALUE
        else _NOT_APPLICABLE_RELEASE_NOTES_BLOCK
    )
```

И в теле f-строки (после секции `# Temporal delta текущего окна`, перед `# Reference-чеклист для этого шага`, т.е. между строками 189 и 191) добавить новую секцию:

```python
---

# Контекст release notes для текущего окна

{release_notes_block}

---
```

- [ ] **Шаг 6: Прогнать тесты**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/test_prompts.py -v`
Expected: PASS, все тесты файла зелёные.

- [ ] **Шаг 7: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/prompts.py arch-docs/tests/workflows/init_arch/test_prompts.py
git commit -m "feat(arch-docs): собрать контекст окна для промпта generate_release_notes"
```

---

### Задача 7: nodes.py — node_generate_release_notes и ретаргет validate_final

- [x] Выполнено
- Мини-отчёт: `node_validate_final` теперь переводит workflow в `generate_release_notes`, а новый `node_generate_release_notes` запускает worker, регистрирует созданный markdown и двигает сессию к подтверждению следующего окна.

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/nodes.py:583-585` (`node_validate_final`), заменить заглушку из Задачи 3
- Изменить: `arch-docs/tests/workflows/init_arch/test_nodes.py`

**Интерфейсы:**
- Потребляет: `KnowledgeArtifactService.collect_worker_artifacts` (уже существует), `StepId.GENERATE_RELEASE_NOTES` (Задача 1).
- Производит: `node_generate_release_notes(state)` — регистрирует файл release notes как артефакт и продвигает сессию на `CONFIRM_NEXT_TEMPORAL_WINDOW`.

- [ ] **Шаг 1: Написать падающий тест**

В `arch-docs/tests/workflows/init_arch/test_nodes.py` добавить (по образцу `test_node_run_knowledge_lint_uses_knowledge_service_without_llm`, строки 577-601, и `test_node_define_scope_uses_guard_and_worker_services`, строки 52-85):

```python
async def test_node_generate_release_notes_registers_artifact_and_advances() -> None:
    state = _make_state()
    guard_service = MagicMock()
    llm_service = MagicMock()
    knowledge_service = MagicMock()
    audit_service = MagicMock()

    llm_service.run_task = AsyncMock(
        return_value=LlmTaskResult(
            task_kind=LlmTaskKind.STEP_EXECUTION,
            step_id=StepId.GENERATE_RELEASE_NOTES,
            created_artifacts=["release-notes/window-0-2024-07-10.md"],
        )
    )
    registered_session = state["session"].model_copy()
    knowledge_service.collect_worker_artifacts = AsyncMock(
        return_value=KnowledgeArtifactResult(
            session=registered_session,
            written_artifacts=["release-notes/window-0-2024-07-10.md"],
        )
    )
    next_session = registered_session.model_copy(
        update={
            "current_step": StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
            "completed_steps": [StepId.GENERATE_RELEASE_NOTES],
        }
    )
    guard_service.advance_step = AsyncMock(return_value=GuardOperationResult(session=next_session))

    with (
        patch("app.workflows.init_arch.nodes.get_guard_service", return_value=guard_service),
        patch("app.workflows.init_arch.nodes.get_llm_worker_service", return_value=llm_service),
        patch("app.workflows.init_arch.nodes.get_knowledge_artifact_service", return_value=knowledge_service),
        patch("app.workflows.init_arch.nodes.get_workflow_audit_service", return_value=audit_service),
    ):
        result = await nodes_module.node_generate_release_notes(state)

    assert result["current_step_id"] == "confirm_next_temporal_window"
    knowledge_service.collect_worker_artifacts.assert_awaited_once_with(
        state["session"],
        step_id=StepId.GENERATE_RELEASE_NOTES,
        created_artifacts=["release-notes/window-0-2024-07-10.md"],
    )
    guard_service.advance_step.assert_awaited_once()
```

- [ ] **Шаг 2: Убедиться, что тест падает**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/test_nodes.py -k "generate_release_notes" -v`
Expected: FAIL — текущая заглушка (Задача 3, шаг 0) не вызывает `knowledge_service.collect_worker_artifacts`, поэтому `assert_awaited_once_with` падает с `AssertionError: Expected ... to have been called once. Called 0 times.`.

- [ ] **Шаг 3: Заменить заглушку на полную реализацию**

В `arch-docs/app/workflows/init_arch/nodes.py` заменить заглушку из Задачи 3 (шаг 0) на:

```python
async def node_generate_release_notes(state: InitArchState) -> dict[str, typing.Any]:
    logger.info("workflow.node.generate_release_notes")
    guard_service = get_guard_service()
    knowledge_service = get_knowledge_artifact_service()
    _record_workflow_event(state, EventType.WORKFLOW_STEP_STARTED, step_id=StepId.GENERATE_RELEASE_NOTES)
    try:
        llm_result = await _run_step_worker(state, StepId.GENERATE_RELEASE_NOTES)
        knowledge_result = await knowledge_service.collect_worker_artifacts(
            state["session"],
            step_id=StepId.GENERATE_RELEASE_NOTES,
            created_artifacts=llm_result.created_artifacts,
        )
        result = await guard_service.advance_step(
            knowledge_result.session,
            StepId.CONFIRM_NEXT_TEMPORAL_WINDOW,
            progress_file_path=state["progress_file_path"],
            note=knowledge_result.summary,
        )
    except Exception as exc:  # noqa: BLE001
        _record_workflow_event(
            state,
            EventType.WORKFLOW_STEP_FAILED,
            step_id=StepId.GENERATE_RELEASE_NOTES,
            error=str(exc),
        )
        return {"step_error": str(exc), "retry_count": state.get("retry_count", 0) + 1}
    _record_workflow_event(
        state,
        EventType.WORKFLOW_STEP_COMPLETED,
        step_id=StepId.GENERATE_RELEASE_NOTES,
        next_step=result.session.current_step.value,
    )
    return _session_update_payload(
        result.session,
        last_llm_result=llm_result,
        last_guard_output=result.bridge_output,
    )
```

Это тот же паттерн, что и `node_refine_features` (строки 474-514) — LLM-воркер, затем `collect_worker_artifacts`, затем `advance_step` — но без `bootstrap_arch_repo` (каталог `release-notes/` уже создан в Задаче 4 при первом bootstrap на шаге `refine_features`).

- [ ] **Шаг 4: Прогнать все тесты nodes.py и graph.py**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch/test_nodes.py tests/workflows/init_arch/test_graph.py -v`
Expected: PASS, все тесты обоих файлов зелёные.

- [ ] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/nodes.py arch-docs/tests/workflows/init_arch/test_nodes.py
git commit -m "feat(arch-docs): реализовать узел node_generate_release_notes"
```

---

### Задача 8: Обновить документацию workflow

- [x] Выполнено
- Мини-отчёт: обновлены `arch-docs/docs/workflows/init.md` и `shared_assets/init_arch/SKILL.md`, чтобы новый шаг и `confirm_next_temporal_window` были отражены в state machine, happy path и mapping reference-файлов.

**Файлы:**
- Изменить: `arch-docs/docs/workflows/init.md:46-58` (список шагов state machine)
- Изменить: `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md` (happy path и таблица маппинга шаг → reference)

**Интерфейсы:** нет (документация, не код).

- [ ] **Шаг 1: Обновить список шагов в docs/workflows/init.md**

В `arch-docs/docs/workflows/init.md:46-58` вставить строку между `validate_final` и `finalize_progress`:

```text
define_scope             -> определить scope анализа и инициализировать workflow session
request_repository_list  -> получить список репозиториев, если он не был передан на старте
prepare_temp_workspace   -> подготовить рабочую временную зону под raw analysis
clone_repositories       -> собрать локальные checkout целевых репозиториев
refresh_main_branches    -> прочитать main branch, remote HEAD и created_at по каждому repo
plan_repository_order    -> выбрать anchor repo, рассчитать snapshot date и target commits
assess_scope_and_domains -> определить масштаб анализа и стратегию разбиения на domains
analyze_repositories     -> пройти repository checklist и собрать технические факты
interview_user           -> остановиться на открытых вопросах и дождаться ответа пользователя
refine_features          -> синтезировать и уточнить feature-level knowledge
build_navigation_index   -> собрать навигационные knowledge artifacts и индексы
run_knowledge_lint       -> проверить knowledge layer на структурные проблемы
validate_final           -> выполнить финальную валидацию workflow результата
generate_release_notes   -> сформировать release notes по всему продукту за это окно
confirm_next_temporal_window -> продвинуться к следующему temporal-окну или завершить анализ
finalize_progress        -> зафиксировать завершение session и закрыть workflow
done                      -> terminal state
```

(Существующий блок ранее не упоминал `confirm_next_temporal_window` вовсе — это уже было расхождение с реальным графом, предшествующее этому плану; раз редактируем этот список, добавляем оба отсутствующих шага, а не только новый, чтобы не оставлять список ещё более неполным.)

- [ ] **Шаг 2: Обновить Standard Happy Path в SKILL.md**

В `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md`, в блоке "Standard Happy Path" (после `run_knowledge_lint` и `validate_final`, перед `finalize_progress`) вставить:

```text
  → run_knowledge_lint
  → validate_final
  → generate_release_notes
  → confirm_next_temporal_window
  → finalize_progress
```

- [ ] **Шаг 3: Добавить строку в таблицу «Маппинг: шаг workflow → reference»**

В `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md`, в таблице после `assess_scope_and_domains`:

```markdown
| Шаг `workflow` | Reference-файл |
|---|---|
| `assess_scope_and_domains` | [checklist-scope-and-domain-assessment.md](references/checklist-scope-and-domain-assessment.md) |
| `generate_release_notes` | [checklist-release-notes.md](references/checklist-release-notes.md) |
```

- [ ] **Шаг 4: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/docs/workflows/init.md arch-docs/app/workflows/shared_assets/init_arch/SKILL.md
git commit -m "docs(arch-docs): описать шаг generate_release_notes в документации init_arch"
```

---

### Задача 9: Полный регрессионный прогон

- [x] Выполнено
- Мини-отчёт: `uv run pytest tests/workflows/init_arch -v` завершился с `200 passed, 1 xfailed`; полный `uv run pytest -v` по `arch-docs` завершился с `424 passed, 1 xfailed, 3 warnings`. Оба ожидаемых `xfail` и warnings существовали вне этой дельты и не блокируют изменение.

**Файлы:** нет (только проверка).

- [ ] **Шаг 1: Прогнать весь пакет тестов init_arch**

Run: `cd arch-docs && uv run pytest tests/workflows/init_arch -v`
Expected: PASS, 0 failed. Если что-то упало вне файлов, изменённых в Задачах 1-8 (например, `test_llm_worker.py`, `test_guard.py`, `test_audit.py` — они уже были изменены в рабочей копии до начала этого плана, см. `git status`), сверить конфликт вручную перед тем как считать план завершённым.

- [ ] **Шаг 2: Прогнать полный набор тестов сервиса**

Run: `cd arch-docs && uv run pytest -v`
Expected: PASS, 0 failed, 0 errors.

- [ ] **Шаг 3: Финальный коммит (если после шагов 1-2 были правки)**

Если регрессионный прогон потребовал точечных исправлений — закоммитить их отдельным коммитом с описанием конкретной причины (не одним общим "fix tests").
