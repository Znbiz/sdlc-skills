# Progress-снепшот workflow и восстановление на другой машине — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Цель:** LangGraph-workflow `init_arch` пишет полное состояние в git-трекаемый YAML-снепшот (`progress_file_path`, внутри `arch_repo_dir`) после каждого перехода шага и на каждом interrupt — а затем этот снепшот можно скормить сервису на **другой машине/деплое**, чтобы он создал новый workflow-run, досоздал LangGraph-чекпоинт "как будто" уже пройденные шаги только что завершились, и продолжил выполнение с того шага, на котором всё остановилось.

**Архитектура:** Postgres (`workflow_runs` + LangGraph checkpointer `AsyncPostgresSaver`) остаётся источником истины во время активного прогона — ретраи/interrupt/resume в рамках одного запуска не меняются. Новый модуль `app/workflows/init_arch/snapshot.py` даёт чистую pydantic-модель `WorkflowSnapshot` + функции dump/parse в YAML и атомарную запись на диск. `_drive_graph_stream()` в `app/services/init_arch_workflow.py` — единственная точка, которая уже срабатывает после каждого node output и на каждом interrupt (там же, где `apply_node_output`/`apply_interrupt` + `persist_workflow_record`), — дополнительно вызывает `graph.aget_state(config)` и пишет снепшот.

Для восстановления на другой машине `run_workflow()` получает необязательный параметр `as_node: str | None` — если он задан, перед стартом стрима вызывается `graph.aupdate_state(config, values, as_node=as_node)`, который досоздаёт checkpoint нового `thread_id` "как будто" узел `as_node` только что отработал; дальше стрим продолжается с `stream_input=None` (LangGraph сам продолжает с последнего checkpoint). Новая сервисная функция `resume_init_arch_workflow_from_snapshot()` парсит YAML, создаёт **новый** `workflow_id`/`WorkflowRecord`, вычисляет `as_node` как последний уже пройденный шаг (`session.completed_steps[-1]`) и планирует фоновую задачу `run_workflow(record, initial_state, as_node=as_node)`. Новый MCP-инструмент `resume_init_arch_from_snapshot` читает YAML-файл с диска и вызывает эту функцию — по аналогии с тем, как существующий `init_arch` MCP-инструмент вызывает `start_init_arch_workflow`.

Почему нельзя просто повторно прогнать граф с `START`, подставив уже заполненный `session`: `plan_repository_order` (`historical.py`) безусловно сбрасывает per-repo поля анализа на каждый прогон — если бы граф реально заново выполнял уже пройденные узлы, весь накопленный прогресс анализа затёрся бы. Сидирование чекпоинта через `aupdate_state(..., as_node=...)` этого избегает: граф начинает выполнение ровно с узла `session.current_step`, уже пройденные узлы не запускаются повторно.

**Стек:** Python 3.14, pydantic v2, PyYAML (уже есть в зависимостях), LangGraph (`CompiledStateGraph.aget_state` / `aupdate_state`), pytest + pytest-asyncio, fastmcp (для MCP-инструмента).

## Общие ограничения

- Код и идентификаторы — на английском; комментарии/документация — на русском, только где действительно неочевидно (конвенция `pylines`, уже действующая в этом репозитории).
- На новую/изменённую логику — тесты, покрывающие дельту; молча оставлять пробелы нельзя.
- `just agent-fix` (`ruff check --fix` + `format`) и `ruff check`/`ruff format --check` должны проходить на каждом изменённом файле; в проекте `select = ["ALL"]`, исключения — в `arch-docs/back/pyproject.toml`; для best-effort try/except по аналогии с `persist_workflow_record` использовать `except Exception as exc:  # noqa: BLE001`.
- Тесты, трогающие БД, требуют локальный тестовый Postgres (`just test-db-up` / `docker compose -f docker-compose.test.yml up -d --wait`); запуск — `uv run --extra dev python -m pytest <путь> -q` из `arch-docs/back`.
- Ретрай/interrupt/resume-семантику **в рамках одного запуска** не трогаем, миграцию БД не добавляем, `git add`/`git commit` не автоматизируем — как и для остальных артефактов арх-репозитория, это делает CLI-агент/пользователь, не backend (проверено: `git commit` нигде в `arch-docs/back/app` не вызывается).
- Восстановленный workflow получает **новый** `workflow_id` (не совпадающий со `snapshot.workflow_id`) — старый `thread_id` в LangGraph checkpointer на новой машине/БД всё равно недоступен, а переиспользование `session_id`/`workflow_id` без гарантии уникальности рискует коллизией, если старый workflow ещё жив где-то ещё.

---

## Структура файлов

- **Создать** `arch-docs/back/app/workflows/init_arch/snapshot.py` — модель `WorkflowSnapshot`, `build_snapshot()`, `dump_snapshot_yaml()`, `parse_snapshot_yaml()`, `write_snapshot_file()`.
- **Создать** `arch-docs/back/tests/workflows/init_arch/test_snapshot.py` — юнит-тесты модуля выше, БД не нужна.
- **Изменить** `arch-docs/back/app/services/init_arch_workflow.py` — хук записи снепшота в `_drive_graph_stream()`; параметр `as_node` в `run_workflow()`; новая функция `resume_init_arch_workflow_from_snapshot()`.
- **Изменить** `arch-docs/back/tests/services/test_init_arch_workflow.py` — `aget_state` в 4 существующих фейковых `_Graph`; новые тесты для хука снепшота, `as_node`-сидирования и rehydrate-функции.
- **Изменить** `arch-docs/back/app/mcp_server.py` — новый MCP-инструмент `resume_init_arch_from_snapshot`.
- **Изменить** `arch-docs/back/tests/mcp/test_mcp_server.py` — тесты нового MCP-инструмента.
- **Изменить** `arch-docs/docs/workflows/init-graph-reference.md` — раздел «Compatibility-поле `progress_file_path`» сейчас утверждает, что файл никогда не пишется; после этого плана это неверно, плюс нужно описать restore-flow.

---

### Task 1: Модель `WorkflowSnapshot` + чистые функции dump/parse

**Файлы:**
- Создать: `arch-docs/back/app/workflows/init_arch/snapshot.py`
- Тест: `arch-docs/back/tests/workflows/init_arch/test_snapshot.py`

**Интерфейсы:**
- Использует: `app.workflows.init_arch.domain.WorkflowSessionRecord` (уже существует).
- Отдаёт (используется в Задаче 2 и 3): `WorkflowSnapshot` (pydantic-модель), `build_snapshot(state: typing.Mapping[str, typing.Any]) -> WorkflowSnapshot`, `dump_snapshot_yaml(snapshot: WorkflowSnapshot) -> str`, `parse_snapshot_yaml(yaml_text: str) -> WorkflowSnapshot`.

- [ ] **Шаг 1: Написать падающие тесты**

```python
# arch-docs/back/tests/workflows/init_arch/test_snapshot.py
from __future__ import annotations

import datetime as dt

import yaml

from app.workflows.init_arch import snapshot as snapshot_module
from app.workflows.init_arch.domain import RepositoryExecution, StepId, WorkflowSessionRecord


def _make_state() -> dict:
    session = WorkflowSessionRecord(
        session_id="wf-1",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.CLONE_REPOSITORIES,
        completed_steps=[StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE],
        repositories=[RepositoryExecution(repository_name="svc-a", created_at=dt.date(2024, 1, 1))],
    )
    return {
        "session_id": "wf-1",
        "session": session,
        "workspace_dir": "/workspace/repo",
        "arch_repo_dir": "/workspace/repo/arch-doc",
        "engine_name": "claude",
        "timeout_seconds": 600,
        "progress_file_path": "/workspace/repo/arch-doc/repo-initialization-progress.yaml",
        "raw_workspace_dir": "/workspace/repo/.temp",
        "last_llm_result": None,
        "last_guard_output": "",
        "step_error": None,
        "retry_count": 0,
    }


def test_build_snapshot_captures_fields_not_present_on_workflow_session_record():
    state = _make_state()

    snapshot = snapshot_module.build_snapshot(state)

    assert snapshot.workflow_id == "wf-1"
    assert snapshot.workspace_dir == "/workspace/repo"
    assert snapshot.arch_repo_dir == "/workspace/repo/arch-doc"
    assert snapshot.engine_name == "claude"
    assert snapshot.timeout_seconds == 600
    assert snapshot.session.current_step is StepId.CLONE_REPOSITORIES
    assert snapshot.schema_version == 1


def test_dump_snapshot_yaml_produces_plain_readable_yaml():
    snapshot = snapshot_module.build_snapshot(_make_state())

    yaml_text = snapshot_module.dump_snapshot_yaml(snapshot)
    parsed = yaml.safe_load(yaml_text)

    assert parsed["workflow_id"] == "wf-1"
    assert parsed["session"]["current_step"] == "clone_repositories"
    assert parsed["session"]["repositories"][0]["repository_name"] == "svc-a"
    assert parsed["session"]["repositories"][0]["created_at"] == "2024-01-01"


def test_dump_then_parse_snapshot_yaml_round_trips():
    original = snapshot_module.build_snapshot(_make_state())

    yaml_text = snapshot_module.dump_snapshot_yaml(original)
    restored = snapshot_module.parse_snapshot_yaml(yaml_text)

    assert restored == original
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/workflows/init_arch/test_snapshot.py -q`
Ожидается: `ModuleNotFoundError: No module named 'app.workflows.init_arch.snapshot'` — модуля ещё нет.

- [ ] **Шаг 3: Написать реализацию**

```python
# arch-docs/back/app/workflows/init_arch/snapshot.py
from __future__ import annotations

import datetime
import typing

import pydantic
import yaml

from app.workflows.init_arch.domain import WorkflowSessionRecord

_SNAPSHOT_SCHEMA_VERSION: typing.Final[int] = 1


class WorkflowSnapshot(pydantic.BaseModel):
    schema_version: int = _SNAPSHOT_SCHEMA_VERSION
    workflow_id: str
    workspace_dir: str
    arch_repo_dir: str
    engine_name: str
    timeout_seconds: int
    updated_at: datetime.datetime
    session: WorkflowSessionRecord


def build_snapshot(state: typing.Mapping[str, typing.Any]) -> WorkflowSnapshot:
    return WorkflowSnapshot(
        workflow_id=state["session_id"],
        workspace_dir=state["workspace_dir"],
        arch_repo_dir=state["arch_repo_dir"],
        engine_name=state["engine_name"],
        timeout_seconds=state["timeout_seconds"],
        updated_at=datetime.datetime.now(datetime.timezone.utc),
        session=state["session"],
    )


def dump_snapshot_yaml(snapshot: WorkflowSnapshot) -> str:
    payload = snapshot.model_dump(mode="json")
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def parse_snapshot_yaml(yaml_text: str) -> WorkflowSnapshot:
    payload = yaml.safe_load(yaml_text)
    return WorkflowSnapshot.model_validate(payload)
```

`state` типизирован как `typing.Mapping[str, typing.Any]`, а не `InitArchState`, чтобы не тянуть импорт `state.py` без необходимости — `build_snapshot` обращается только к ключам по имени, а Задача 3 передаёт сюда `dict` из `graph.aget_state(...).values`, а не типизированный `TypedDict`-инстанс.

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/workflows/init_arch/test_snapshot.py -q`
Ожидается: `3 passed`

- [ ] **Шаг 5: Линт**

Команда: `cd arch-docs/back && uv run --extra dev ruff check app/workflows/init_arch/snapshot.py tests/workflows/init_arch/test_snapshot.py && uv run --extra dev ruff format --check app/workflows/init_arch/snapshot.py tests/workflows/init_arch/test_snapshot.py`
Ожидается: `All checks passed!` / `2 files already formatted`

- [ ] **Шаг 6: Коммит**

```bash
cd arch-docs/back
git add app/workflows/init_arch/snapshot.py tests/workflows/init_arch/test_snapshot.py
git commit -m "feat(arch-docs): добавить WorkflowSnapshot модель и YAML dump/parse"
```

---

### Task 2: Атомарная запись файла с best-effort обработкой ошибок

**Файлы:**
- Изменить: `arch-docs/back/app/workflows/init_arch/snapshot.py`
- Тест: `arch-docs/back/tests/workflows/init_arch/test_snapshot.py`

**Интерфейсы:**
- Использует: `build_snapshot()`, `dump_snapshot_yaml()` из Задачи 1.
- Отдаёт (используется в Задаче 3): `write_snapshot_file(state: typing.Mapping[str, typing.Any]) -> None`. No-op, если у `state` нет непустого `progress_file_path`. Никогда не бросает исключение — при любой ошибке логирует `structlog`-warning `"workflow.snapshot_persist_failed"`, ровно как существующий `"workflow.persist_failed"` в `persist_workflow_record()`.

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в `arch-docs/back/tests/workflows/init_arch/test_snapshot.py`:

```python
import structlog.testing


def test_write_snapshot_file_writes_yaml_to_progress_file_path(tmp_path):
    progress_file = tmp_path / "arch-doc" / "repo-initialization-progress.yaml"
    state = _make_state()
    state["progress_file_path"] = str(progress_file)

    snapshot_module.write_snapshot_file(state)

    assert progress_file.exists()
    restored = snapshot_module.parse_snapshot_yaml(progress_file.read_text(encoding="utf-8"))
    assert restored.workflow_id == "wf-1"


def test_write_snapshot_file_overwrites_previous_content(tmp_path):
    progress_file = tmp_path / "progress.yaml"
    state = _make_state()
    state["progress_file_path"] = str(progress_file)

    snapshot_module.write_snapshot_file(state)
    state["session"] = state["session"].model_copy(update={"current_step": StepId.REFRESH_MAIN_BRANCHES})
    snapshot_module.write_snapshot_file(state)

    restored = snapshot_module.parse_snapshot_yaml(progress_file.read_text(encoding="utf-8"))
    assert restored.session.current_step is StepId.REFRESH_MAIN_BRANCHES


def test_write_snapshot_file_noop_when_progress_file_path_missing():
    state = _make_state()
    state["progress_file_path"] = ""

    snapshot_module.write_snapshot_file(state)  # не должно бросать исключение


def test_write_snapshot_file_swallows_errors_and_logs_warning(tmp_path):
    unwritable_dir = tmp_path / "not-a-directory"
    unwritable_dir.write_text("i am a file, not a directory")
    state = _make_state()
    state["progress_file_path"] = str(unwritable_dir / "progress.yaml")

    with structlog.testing.capture_logs() as captured:
        snapshot_module.write_snapshot_file(state)  # не должно бросать исключение

    assert any(entry["event"] == "workflow.snapshot_persist_failed" for entry in captured)
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/workflows/init_arch/test_snapshot.py -q`
Ожидается: `AttributeError: module 'app.workflows.init_arch.snapshot' has no attribute 'write_snapshot_file'`

- [ ] **Шаг 3: Написать реализацию**

Добавить в `arch-docs/back/app/workflows/init_arch/snapshot.py`:

```python
import pathlib
import tempfile

import structlog

logger = structlog.get_logger()


def write_snapshot_file(state: typing.Mapping[str, typing.Any]) -> None:
    progress_file_path = state.get("progress_file_path", "")
    if not progress_file_path:
        return
    try:
        yaml_text = dump_snapshot_yaml(build_snapshot(state))
        target_path = pathlib.Path(progress_file_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=target_path.parent, delete=False, suffix=".tmp", encoding="utf-8"
        ) as tmp_file:
            tmp_file.write(yaml_text)
            tmp_path = pathlib.Path(tmp_file.name)
        tmp_path.replace(target_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "workflow.snapshot_persist_failed",
            workflow_id=state.get("session_id", ""),
            error=str(exc),
        )
```

Добавить соответствующие импорты (`import pathlib`, `import tempfile`, `import structlog`) в начало файла рядом с уже существующими `import datetime`/`import typing`/`import pydantic`/`import yaml`.

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/workflows/init_arch/test_snapshot.py -q`
Ожидается: `7 passed`

- [ ] **Шаг 5: Линт**

Команда: `cd arch-docs/back && uv run --extra dev ruff check app/workflows/init_arch/snapshot.py tests/workflows/init_arch/test_snapshot.py && uv run --extra dev ruff format --check app/workflows/init_arch/snapshot.py tests/workflows/init_arch/test_snapshot.py`
Ожидается: `All checks passed!` / `2 files already formatted`

- [ ] **Шаг 6: Коммит**

```bash
cd arch-docs/back
git add app/workflows/init_arch/snapshot.py tests/workflows/init_arch/test_snapshot.py
git commit -m "feat(arch-docs): атомарная запись WorkflowSnapshot на диск с best-effort обработкой ошибок"
```

---

### Task 3: Хук записи снепшота в `_drive_graph_stream`

**Файлы:**
- Изменить: `arch-docs/back/app/services/init_arch_workflow.py:731-768` (`_drive_graph_stream`)
- Изменить: `arch-docs/back/tests/services/test_init_arch_workflow.py` (4 фейковых `_Graph` + 1 новый тест)

**Интерфейсы:**
- Использует: `app.workflows.init_arch.snapshot.write_snapshot_file` (Задача 2).
- Отдаёт: сигнатура `_drive_graph_stream` не меняется — `(record, graph, config, stream_input) -> bool`. Полагается на стандартный API `CompiledStateGraph.aget_state(config)`, возвращающий объект с `.values`, равным текущему `InitArchState`.

- [ ] **Шаг 1: Обновить фейки в тестах заранее**

В `arch-docs/back/tests/services/test_init_arch_workflow.py` в каждый из 4 `class _Graph:` (у них сейчас есть только `async def astream(self, _state, *, config): ...`) добавить метод сразу после `astream`:

```python
    async def aget_state(self, config):
        del config
        return types.SimpleNamespace(values={})
```

(`types` уже импортирован в этом файле.) `values={}` означает, что `write_snapshot_file` не увидит ключ `progress_file_path`, `.get("progress_file_path", "")` даст `""`, и запись будет no-op — эти 4 существующих теста ничего не должны знать про снепшоты.

- [ ] **Шаг 2: Прогнать существующий набор тестов, чтобы убедиться, что он зелёный перед хуком**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py -q`
Ожидается: всё проходит (шаг просто подтверждает, что фейки компилируются/подходят под старый код до правки `_drive_graph_stream`).

- [ ] **Шаг 3: Написать новый падающий тест на сам хук**

Добавить в `arch-docs/back/tests/services/test_init_arch_workflow.py`, рядом с первым happy-path тестом на `_Graph`:

```python
async def test_run_workflow_writes_progress_snapshot_after_each_step(monkeypatch, tmp_path):
    progress_file = tmp_path / "arch-doc" / "repo-initialization-progress.yaml"
    initial_session = WorkflowSessionRecord(
        session_id="wf-snapshot",
        product_name="Prod",
        analysis_scope="full",
    )
    advanced_session = initial_session.model_copy(
        update={"current_step": StepId.REQUEST_REPOSITORY_LIST, "completed_steps": [StepId.DEFINE_SCOPE]}
    )
    final_session = advanced_session.model_copy(update={"current_step": StepId.DONE})
    record = WorkflowRecord(workflow_id="wf-snapshot", conversation_id="conv-snapshot", session=initial_session)

    state_after_define_scope = {
        "session_id": "wf-snapshot",
        "session": advanced_session,
        "workspace_dir": str(tmp_path),
        "arch_repo_dir": str(tmp_path / "arch-doc"),
        "engine_name": "claude",
        "timeout_seconds": 600,
        "progress_file_path": str(progress_file),
    }
    state_after_finalize = {**state_after_define_scope, "session": final_session}

    class _Graph:
        def __init__(self) -> None:
            self._states = iter([state_after_define_scope, state_after_finalize])

        async def astream(self, _state, *, config):
            assert config == {"configurable": {"thread_id": "wf-snapshot"}}
            yield {"define_scope": {"session": advanced_session, "current_step_id": "request_repository_list"}}
            yield {"finalize_progress": {"session": final_session, "current_step_id": "done"}}

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values=next(self._states))

    async def _fake_persist(current: WorkflowRecord) -> None:
        del current

    def _compile_graph(checkpointer):
        del checkpointer
        return _Graph()

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", _compile_graph)
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", _fake_persist)

    await workflow_module.run_workflow(
        record,
        workflow_module.InitArchState(
            session_id=initial_session.session_id,
            session=initial_session,
            workspace_dir=str(tmp_path),
            arch_repo_dir=str(tmp_path / "arch-doc"),
            engine_name="claude",
            timeout_seconds=600,
            progress_file_path=str(progress_file),
            last_llm_result=None,
            last_guard_output="",
            step_error=None,
            retry_count=0,
        ),
    )

    assert progress_file.exists()
    from app.workflows.init_arch.snapshot import parse_snapshot_yaml

    restored = parse_snapshot_yaml(progress_file.read_text(encoding="utf-8"))
    assert restored.session.current_step is StepId.DONE
```

- [ ] **Шаг 4: Запустить тест и убедиться, что он падает**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py::test_run_workflow_writes_progress_snapshot_after_each_step -q`
Ожидается: `FAILED` на `assert progress_file.exists()` → `False` (хука ещё нет).

- [ ] **Шаг 5: Реализовать хук**

В `arch-docs/back/app/services/init_arch_workflow.py` добавить импорт:

```python
from app.workflows.init_arch.snapshot import write_snapshot_file
```

(рядом с существующим `from app.workflows.init_arch.state import InitArchState`). Затем изменить `_drive_graph_stream`:

```python
async def _drive_graph_stream(
    record: WorkflowRecord, graph: typing.Any, config: dict[str, typing.Any], stream_input: typing.Any
) -> bool:
    """Advance the graph until it interrupts or reaches END.

    Returns True if the run should be treated as failed: the graph's own retry/error routing
    (see `_route_after_node` in graph.py) can exhaust retries and route through the
    `handle_error` node straight to END without raising a Python exception, so a clean
    `astream` completion does not by itself mean the workflow succeeded.
    """
    reached_handle_error = False
    last_step_error: str | None = None

    async for event in graph.astream(stream_input, config=config):
        for node_name, node_output in event.items():
            if node_name == "__interrupt__":
                apply_interrupt(record, node_output)
                await persist_workflow_record(record)
                await _write_progress_snapshot(graph, config)
                logger.info(
                    "workflow.interrupted",
                    workflow_id=record.workflow_id,
                    interrupt=record.pending_interrupt,
                )
                return False
            # LangGraph reports a node that returned `{}` (no state update) as `None` here,
            # not `{}` - so this must be checked before the isinstance/apply_node_output gate.
            if node_name == _GRAPH_ERROR_NODE_NAME:
                reached_handle_error = True
            if not isinstance(node_output, dict):
                continue
            if node_output.get("step_error"):
                last_step_error = node_output["step_error"]
            apply_node_output(record, node_output)
            await persist_workflow_record(record)
            await _write_progress_snapshot(graph, config)

    if reached_handle_error:
        record.error_message = last_step_error or "Workflow step failed after exhausting retries"
    return reached_handle_error


async def _write_progress_snapshot(graph: typing.Any, config: dict[str, typing.Any]) -> None:
    state_snapshot = await graph.aget_state(config)
    write_snapshot_file(state_snapshot.values)
```

Почему именно `graph.aget_state(config)`, а не проброс `engine_name`/`timeout_seconds` через параметры функций: `_drive_graph_stream` общий и для `run_workflow` (свежий старт — там полный `InitArchState` под рукой), и для `resume_workflow_task` (resume после interrupt — сегодня он **не** восстанавливает `InitArchState` целиком, см. Задачу 5). `graph.aget_state(config)` отдаёт полное текущее состояние из checkpointer'а вне зависимости от того, кто именно ведёт стрим — одна точка хука работает для обоих без изменения их сигнатур.

- [ ] **Шаг 6: Запустить тест и убедиться, что он проходит**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py::test_run_workflow_writes_progress_snapshot_after_each_step -q`
Ожидается: `1 passed`

- [ ] **Шаг 7: Прогнать весь файл тестов сервиса, чтобы поймать регрессии**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py -q`
Ожидается: всё зелёное, включая 4 теста с изменёнными фейками.

- [ ] **Шаг 8: Линт**

Команда: `cd arch-docs/back && uv run --extra dev ruff check app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py && uv run --extra dev ruff format --check app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py`
Ожидается: `All checks passed!` / `2 files already formatted`

- [ ] **Шаг 9: Коммит**

```bash
cd arch-docs/back
git add app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py
git commit -m "feat(arch-docs): писать progress-снепшот в arch_repo_dir после каждого шага графа"
```

---

### Task 4: `run_workflow` умеет сидировать checkpoint через `as_node`

**Файлы:**
- Изменить: `arch-docs/back/app/services/init_arch_workflow.py:771-805` (`run_workflow`)
- Изменить: `arch-docs/back/tests/services/test_init_arch_workflow.py`

**Интерфейсы:**
- Отдаёт (используется в Задаче 5): `run_workflow(record: WorkflowRecord, initial_state: InitArchState, *, as_node: str | None = None) -> None`. При `as_node=None` поведение **не меняется** (значение по умолчанию, все существующие вызовы совместимы). При заданном `as_node` вызывается `graph.aupdate_state(config, dict(initial_state), as_node=as_node)`, и в `graph.astream(...)` передаётся `None` вместо `initial_state`.

- [ ] **Шаг 1: Написать падающий тест**

Добавить в `arch-docs/back/tests/services/test_init_arch_workflow.py`:

```python
async def test_run_workflow_seeds_checkpoint_via_aupdate_state_when_as_node_given(monkeypatch):
    session = WorkflowSessionRecord(
        session_id="wf-seed",
        product_name="Prod",
        analysis_scope="full",
        current_step=StepId.CLONE_REPOSITORIES,
        completed_steps=[StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE],
    )
    record = WorkflowRecord(workflow_id="wf-seed", conversation_id="conv-seed", session=session)
    final_session = session.model_copy(update={"current_step": StepId.DONE})
    aupdate_state_calls = []

    class _Graph:
        async def aupdate_state(self, config, values, *, as_node):
            aupdate_state_calls.append((config, values, as_node))

        async def astream(self, state_input, *, config):
            assert state_input is None
            yield {"finalize_progress": {"session": final_session, "current_step_id": "done"}}

        async def aget_state(self, config):
            del config
            return types.SimpleNamespace(values={})

    def _compile_graph(checkpointer):
        del checkpointer
        return _Graph()

    monkeypatch.setattr("app.services.init_arch_workflow.get_checkpointer", AsyncMock(return_value="checkpoint"))
    monkeypatch.setattr("app.services.init_arch_workflow.compile_graph", _compile_graph)
    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())

    initial_state = workflow_module.InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir="/workspace",
        arch_repo_dir="/workspace/arch-doc",
        engine_name="claude",
        timeout_seconds=60,
        progress_file_path="/workspace/arch-doc/progress.yaml",
        last_llm_result=None,
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )

    await workflow_module.run_workflow(record, initial_state, as_node="prepare_temp_workspace")

    assert len(aupdate_state_calls) == 1
    seeded_config, seeded_values, seeded_as_node = aupdate_state_calls[0]
    assert seeded_config == {"configurable": {"thread_id": "wf-seed"}}
    assert seeded_values["session"] == session
    assert seeded_as_node == "prepare_temp_workspace"
    assert record.workflow_status is WorkflowStatus.SUCCESS
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py::test_run_workflow_seeds_checkpoint_via_aupdate_state_when_as_node_given -q`
Ожидается: `TypeError: run_workflow() got an unexpected keyword argument 'as_node'`

- [ ] **Шаг 3: Реализовать**

Изменить сигнатуру и начало `run_workflow` в `arch-docs/back/app/services/init_arch_workflow.py`:

```python
async def run_workflow(
    record: WorkflowRecord, initial_state: InitArchState, *, as_node: str | None = None
) -> None:
    registry = get_workflow_registry()
    try:
        checkpointer = await get_checkpointer()
        graph = compile_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": record.workflow_id}}

        if as_node is not None:
            await graph.aupdate_state(config, dict(initial_state), as_node=as_node)
            stream_input: typing.Any = None
        else:
            stream_input = initial_state

        failed = await _drive_graph_stream(record, graph, config, stream_input)
        if record.workflow_status == WorkflowStatus.INTERRUPTED:
            return

        record.workflow_status = WorkflowStatus.FAILED if failed else WorkflowStatus.SUCCESS
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        if failed:
            logger.error("workflow.failed", workflow_id=record.workflow_id, error=record.error_message)
        else:
            logger.info("workflow.completed", workflow_id=record.workflow_id)
    except asyncio.CancelledError:
        record.workflow_status = WorkflowStatus.CANCELLED
        record.error_message = "Workflow cancelled"
        record.pending_interrupt = None
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        logger.info("workflow.cancelled", workflow_id=record.workflow_id)
        raise
    except Exception as exc:  # noqa: BLE001
        record.workflow_status = WorkflowStatus.FAILED
        record.error_message = str(exc)
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        logger.error("workflow.failed", workflow_id=record.workflow_id, error=str(exc))
    finally:
        registry[record.workflow_id] = record
```

(Тело `try`/`except`/`finally` не меняется — меняются только первые несколько строк внутри `try`, которые решают, что передать в `_drive_graph_stream`.)

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py::test_run_workflow_seeds_checkpoint_via_aupdate_state_when_as_node_given -q`
Ожидается: `1 passed`

- [ ] **Шаг 5: Прогнать весь файл тестов сервиса**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py -q`
Ожидается: всё зелёное — старые вызовы `run_workflow(record, state)` без `as_node` ведут себя как раньше (значение по умолчанию `None`).

- [ ] **Шаг 6: Линт**

Команда: `cd arch-docs/back && uv run --extra dev ruff check app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py && uv run --extra dev ruff format --check app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py`
Ожидается: `All checks passed!` / `2 files already formatted`

- [ ] **Шаг 7: Коммит**

```bash
cd arch-docs/back
git add app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py
git commit -m "feat(arch-docs): run_workflow умеет сидировать LangGraph checkpoint через as_node"
```

---

### Task 5: Сервисная функция `resume_init_arch_workflow_from_snapshot`

**Файлы:**
- Изменить: `arch-docs/back/app/services/init_arch_workflow.py`
- Изменить: `arch-docs/back/tests/services/test_init_arch_workflow.py`

**Интерфейсы:**
- Использует: `parse_snapshot_yaml` (Задача 1), `run_workflow(..., as_node=...)` (Задача 4), `_resolve_init_arch_paths` (уже существует).
- Отдаёт (используется в Задаче 6): `async def resume_init_arch_workflow_from_snapshot(yaml_text: str, *, workspace_dir: str | None = None, arch_repo_dir: str | None = None, engine_name: str | None = None, timeout_seconds: int | None = None, conversation_id: str | None = None) -> WorkflowRecord`.

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в `arch-docs/back/tests/services/test_init_arch_workflow.py` (по образцу существующего `test_start_init_arch_workflow_registers_record_and_schedules_task`):

```python
def _make_snapshot_yaml(*, current_step: StepId, completed_steps: list[StepId]) -> str:
    from app.workflows.init_arch.snapshot import WorkflowSnapshot, dump_snapshot_yaml

    session = WorkflowSessionRecord(
        session_id="wf-original",
        product_name="Prod",
        analysis_scope="full",
        current_step=current_step,
        completed_steps=completed_steps,
        repositories=[RepositoryExecution(repository_name="svc-a")],
    )
    snapshot = WorkflowSnapshot(
        workflow_id="wf-original",
        workspace_dir="/old/workspace",
        arch_repo_dir="/old/workspace/arch-doc",
        engine_name="claude",
        timeout_seconds=600,
        updated_at=datetime.datetime.now(datetime.timezone.utc),
        session=session,
    )
    return dump_snapshot_yaml(snapshot)


async def test_resume_init_arch_workflow_from_snapshot_schedules_task_with_as_node(monkeypatch):
    yaml_text = _make_snapshot_yaml(
        current_step=StepId.CLONE_REPOSITORIES,
        completed_steps=[StepId.DEFINE_SCOPE, StepId.REQUEST_REPOSITORY_LIST, StepId.PREPARE_TEMP_WORKSPACE],
    )
    created_tasks = []
    real_create_task = asyncio.create_task

    def _fake_create_task(coro):
        task = real_create_task(coro)
        created_tasks.append(task)
        return task

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", _fake_create_task)
    run_workflow_mock = AsyncMock()
    monkeypatch.setattr("app.services.init_arch_workflow.run_workflow", run_workflow_mock)

    record = await workflow_module.resume_init_arch_workflow_from_snapshot(
        yaml_text,
        workspace_dir="/new/workspace",
        arch_repo_dir="/new/workspace/arch-doc",
    )

    assert record.workflow_id != "wf-original"
    assert record.session.session_id == record.workflow_id
    assert record.session.current_step is StepId.CLONE_REPOSITORIES
    assert [repo.repository_name for repo in record.session.repositories] == ["svc-a"]
    assert created_tasks
    run_workflow_mock.assert_awaited_once()
    _, kwargs = run_workflow_mock.await_args
    assert kwargs["as_node"] == "prepare_temp_workspace"
    for task in created_tasks:
        task.cancel()


async def test_resume_init_arch_workflow_from_snapshot_already_done_marks_success_without_task(monkeypatch):
    yaml_text = _make_snapshot_yaml(
        current_step=StepId.DONE,
        completed_steps=[StepId.FINALIZE_PROGRESS],
    )

    monkeypatch.setattr("app.services.init_arch_workflow.persist_workflow_record", AsyncMock())
    create_task_mock = unittest.mock.MagicMock()
    monkeypatch.setattr("app.services.init_arch_workflow.asyncio.create_task", create_task_mock)

    record = await workflow_module.resume_init_arch_workflow_from_snapshot(
        yaml_text,
        workspace_dir="/new/workspace",
        arch_repo_dir="/new/workspace/arch-doc",
    )

    assert record.workflow_status == WorkflowStatus.SUCCESS
    create_task_mock.assert_not_called()
```

(Если `unittest.mock` ещё не импортирован в файле — добавить `import unittest.mock` рядом с остальными импортами в шапке теста; `datetime` уже импортирован для других тестов этого файла.)

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py -k resume_init_arch_workflow_from_snapshot -q`
Ожидается: `AttributeError: module 'app.services.init_arch_workflow' has no attribute 'resume_init_arch_workflow_from_snapshot'`

- [ ] **Шаг 3: Написать реализацию**

Добавить `StepId` в существующий импорт домена и добавить импорт `parse_snapshot_yaml`:

```python
from app.workflows.init_arch.domain import RepositoryExecution, StepId, WorkflowSessionRecord
...
from app.workflows.init_arch.snapshot import parse_snapshot_yaml, write_snapshot_file
```

Добавить функцию в `arch-docs/back/app/services/init_arch_workflow.py` рядом с `start_init_arch_workflow`:

```python
async def resume_init_arch_workflow_from_snapshot(
    yaml_text: str,
    *,
    workspace_dir: str | None = None,
    arch_repo_dir: str | None = None,
    engine_name: str | None = None,
    timeout_seconds: int | None = None,
    conversation_id: str | None = None,
) -> WorkflowRecord:
    snapshot = parse_snapshot_yaml(yaml_text)
    resolved_workspace_dir, resolved_arch_repo_dir, resolved_raw_workspace_dir = _resolve_init_arch_paths(
        workspace_dir=workspace_dir or snapshot.workspace_dir,
        arch_repo_dir=arch_repo_dir or snapshot.arch_repo_dir,
    )
    workflow_id = str(uuid.uuid4())
    progress_file_path = f"{resolved_arch_repo_dir}/repo-initialization-progress.yaml"
    session = snapshot.session.model_copy(update={"session_id": workflow_id})

    record = WorkflowRecord(
        workflow_id=workflow_id,
        conversation_id=conversation_id or workflow_id,
        session=session,
        workspace_dir=resolved_workspace_dir,
        arch_repo_dir=resolved_arch_repo_dir,
        current_step_id=session.current_step.value,
        completed_steps=[step.value for step in session.completed_steps],
    )
    registry = get_workflow_registry()
    registry[workflow_id] = record
    await persist_workflow_record(record)

    if session.current_step is StepId.DONE:
        record.workflow_status = WorkflowStatus.SUCCESS
        record.updated_at = utcnow()
        await persist_workflow_record(record)
        logger.info("workflow.rehydrated_already_done", workflow_id=workflow_id, source_workflow_id=snapshot.workflow_id)
        return record

    initial_state = InitArchState(
        session_id=session.session_id,
        session=session,
        workspace_dir=resolved_workspace_dir,
        raw_workspace_dir=resolved_raw_workspace_dir,
        arch_repo_dir=resolved_arch_repo_dir,
        engine_name=engine_name or snapshot.engine_name,
        timeout_seconds=timeout_seconds or snapshot.timeout_seconds,
        progress_file_path=progress_file_path,
        last_llm_result=None,
        last_guard_output="",
        step_error=None,
        retry_count=0,
    )
    as_node = session.completed_steps[-1].value if session.completed_steps else None

    task = asyncio.create_task(run_workflow(record, initial_state, as_node=as_node))
    record.asyncio_task = task
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    logger.info(
        "workflow.rehydrated",
        workflow_id=workflow_id,
        source_workflow_id=snapshot.workflow_id,
        as_node=as_node,
    )
    return record
```

`as_node = None` (когда `completed_steps` пуст — снепшот снят до первого перехода) означает, что сидирование не нужно: `run_workflow` пойдёт по обычной ветке `stream_input = initial_state`, граф стартует с `START` как обычный новый прогон — это безопасно, потому что ничего ещё не выполнялось и нечего портить повторным прогоном.

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py -k resume_init_arch_workflow_from_snapshot -q`
Ожидается: `2 passed`

- [ ] **Шаг 5: Прогнать весь файл тестов сервиса**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/services/test_init_arch_workflow.py -q`
Ожидается: всё зелёное.

- [ ] **Шаг 6: Линт**

Команда: `cd arch-docs/back && uv run --extra dev ruff check app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py && uv run --extra dev ruff format --check app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py`
Ожидается: `All checks passed!` / `2 files already formatted`

- [ ] **Шаг 7: Коммит**

```bash
cd arch-docs/back
git add app/services/init_arch_workflow.py tests/services/test_init_arch_workflow.py
git commit -m "feat(arch-docs): resume_init_arch_workflow_from_snapshot — восстановление workflow из YAML-снепшота"
```

---

### Task 6: MCP-инструмент `resume_init_arch_from_snapshot`

**Файлы:**
- Изменить: `arch-docs/back/app/mcp_server.py`
- Изменить: `arch-docs/back/tests/mcp/test_mcp_server.py`

**Интерфейсы:**
- Использует: `resume_init_arch_workflow_from_snapshot` (Задача 5).
- Отдаёт: MCP-инструмент `resume_init_arch_from_snapshot(repo_path: str, arch_repo_dir: str | None = None, workspace_dir: str | None = None, engine_name: str | None = None, timeout_seconds: int | None = None) -> dict`, форма ответа идентична `init_arch` (`workflow_id`, `workflow_status`, `current_step_id`, `created_at`).

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в `arch-docs/back/tests/mcp/test_mcp_server.py`:

```python
import pathlib

from app.mcp_server import UPDATE_ARCH_PROMPT_BASE, init_arch, query, resume_init_arch_from_snapshot, run_cli_subprocess, update_arch


class TestResumeInitArchFromSnapshot:
    async def test_reads_snapshot_and_delegates_to_backend(self, tmp_path) -> None:
        arch_repo_dir = tmp_path / "arch-doc"
        arch_repo_dir.mkdir()
        progress_file = arch_repo_dir / "repo-initialization-progress.yaml"
        progress_file.write_text("schema_version: 1\n", encoding="utf-8")

        with unittest.mock.patch(
            "app.mcp_server.resume_init_arch_workflow_from_snapshot", new_callable=unittest.mock.AsyncMock
        ) as mock_resume:
            mock_resume.return_value = types.SimpleNamespace(
                workflow_id="wf-resumed",
                workflow_status="running",
                current_step_id="clone_repositories",
                created_at=types.SimpleNamespace(isoformat=lambda: "2026-07-18T00:00:00+00:00"),
            )

            result = await resume_init_arch_from_snapshot(
                repo_path=str(tmp_path), arch_repo_dir=str(arch_repo_dir)
            )

        assert result["workflow_id"] == "wf-resumed"
        assert result["current_step_id"] == "clone_repositories"
        mock_resume.assert_awaited_once()
        kwargs = mock_resume.await_args.kwargs
        assert kwargs["arch_repo_dir"] == str(arch_repo_dir)
        assert kwargs["workspace_dir"] == str(tmp_path)

    async def test_raises_when_snapshot_file_missing(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            await resume_init_arch_from_snapshot(repo_path=str(tmp_path))
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/mcp/test_mcp_server.py -k ResumeInitArchFromSnapshot -q`
Ожидается: `ImportError: cannot import name 'resume_init_arch_from_snapshot' from 'app.mcp_server'`

- [ ] **Шаг 3: Написать реализацию**

В `arch-docs/back/app/mcp_server.py` изменить импорт и добавить новый инструмент:

```python
from app.services.init_arch_workflow import resume_init_arch_workflow_from_snapshot, start_init_arch_workflow
```

```python
@mcp_server.tool()
async def resume_init_arch_from_snapshot(
    repo_path: str,
    arch_repo_dir: str | None = None,
    workspace_dir: str | None = None,
    engine_name: str | None = None,
    timeout_seconds: int | None = None,
) -> dict:
    """Продолжает backend workflow init_arch с YAML-снепшота прогресса
    (repo-initialization-progress.yaml) — например, после переноса
    арх-репозитория на другую машину."""
    repo_dir = pathlib.Path(repo_path)
    resolved_arch_repo_dir = pathlib.Path(arch_repo_dir) if arch_repo_dir else repo_dir / "arch-doc"
    progress_file = resolved_arch_repo_dir / "repo-initialization-progress.yaml"
    logger.info(
        "mcp.resume_init_arch_from_snapshot.called",
        repo_path=repo_path,
        progress_file=str(progress_file),
    )
    if not progress_file.exists():
        raise FileNotFoundError(f"progress snapshot not found: {progress_file}")

    yaml_text = progress_file.read_text(encoding="utf-8")
    record = await resume_init_arch_workflow_from_snapshot(
        yaml_text,
        workspace_dir=workspace_dir or str(repo_dir),
        arch_repo_dir=str(resolved_arch_repo_dir),
        engine_name=engine_name,
        timeout_seconds=timeout_seconds,
    )
    return {
        "workflow_id": record.workflow_id,
        "workflow_status": record.workflow_status,
        "current_step_id": record.current_step_id,
        "created_at": record.created_at.isoformat(),
    }
```

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/mcp/test_mcp_server.py -k ResumeInitArchFromSnapshot -q`
Ожидается: `2 passed`

- [ ] **Шаг 5: Прогнать весь файл тестов MCP**

Команда: `cd arch-docs/back && uv run --extra dev python -m pytest tests/mcp/test_mcp_server.py -q`
Ожидается: всё зелёное.

- [ ] **Шаг 6: Линт**

Команда: `cd arch-docs/back && uv run --extra dev ruff check app/mcp_server.py tests/mcp/test_mcp_server.py && uv run --extra dev ruff format --check app/mcp_server.py tests/mcp/test_mcp_server.py`
Ожидается: `All checks passed!` / `2 files already formatted`

- [ ] **Шаг 7: Коммит**

```bash
cd arch-docs/back
git add app/mcp_server.py tests/mcp/test_mcp_server.py
git commit -m "feat(arch-docs): MCP-инструмент resume_init_arch_from_snapshot"
```

---

### Task 7: Обновить документацию

**Файлы:**
- Изменить: `arch-docs/docs/workflows/init-graph-reference.md` (раздел «Compatibility-поле `progress_file_path`» и пункт 6 в «Известные несостыковки»)

**Интерфейсы:** нет — только документация.

- [ ] **Шаг 1: Переписать раздел**

Найти раздел `## Compatibility-поле \`progress_file_path\`` в `arch-docs/docs/workflows/init-graph-reference.md`. Он сейчас утверждает, что файл никогда не создаётся и не пишется. Заменить тело раздела на:

```markdown
## Progress-снепшот `progress_file_path` и восстановление на другой машине

`progress_file_path` (`{arch_repo_dir}/repo-initialization-progress.yaml`, формируется один раз в
[init_arch_workflow.py:946](../../back/app/services/init_arch_workflow.py#L946)) реально пишется —
не самой нодой графа, а централизованным хуком в `_drive_graph_stream()`
([init_arch_workflow.py](../../back/app/services/init_arch_workflow.py)), который срабатывает после
**каждого** node output и на каждом `__interrupt__`, тем же способом, каким пишется `workflow_runs`
(`persist_workflow_record`). Формат — YAML-сериализация
[`WorkflowSnapshot`](../../back/app/workflows/init_arch/snapshot.py): `schema_version`,
`workflow_id`, `workspace_dir`, `arch_repo_dir`, `engine_name`, `timeout_seconds`, `updated_at`,
`session` (полный `WorkflowSessionRecord`). Запись — best-effort и атомарная (временный файл +
`os.replace()`); ошибка логируется как `workflow.snapshot_persist_failed` и не прерывает workflow —
тот же паттерн, что и `workflow.persist_failed` у `persist_workflow_record`.

**Canonical state по-прежнему Postgres** (`workflow_runs` + LangGraph checkpointer) — этот файл не
участвует в retry/interrupt/resume рантайме **текущего** запуска. Его основное назначение —
человекочитаемый, диффуемый, коммитящийся в git снепшот прогресса рядом с остальными
knowledge-артефактами в `arch_repo_dir`.

**Восстановление на другой машине.** MCP-инструмент
[`resume_init_arch_from_snapshot`](../../back/app/mcp_server.py) читает этот файл с диска и вызывает
[`resume_init_arch_workflow_from_snapshot()`](../../back/app/services/init_arch_workflow.py), которая:
1. парсит YAML в `WorkflowSnapshot`;
2. создаёт **новый** `workflow_id`/`WorkflowRecord` (старый `thread_id` в checkpointer'е новой
   машины/БД всё равно недоступен);
3. если `session.current_step` уже `DONE` — сразу помечает запись `SUCCESS`, фоновую задачу не
   запускает;
4. иначе вычисляет `as_node = session.completed_steps[-1]` и запускает
   `run_workflow(record, initial_state, as_node=as_node)`.

`run_workflow` при заданном `as_node` сначала вызывает `graph.aupdate_state(config, values,
as_node=as_node)` — это досоздаёт LangGraph checkpoint нового `thread_id` «как будто» узел
`as_node` только что отработал, — и только потом стримит дальше с `stream_input=None` (LangGraph
продолжает с последнего checkpoint). Это принципиально не то же самое, что заново прогнать граф с
`START`, подставив уже заполненный `session`: `plan_repository_order` (`historical.py`) безусловно
сбрасывает per-repo поля анализа на каждый прогон, поэтому наивный replay уничтожил бы уже
накопленный прогресс. Сидирование через `as_node` этого избегает — уже пройденные узлы не
выполняются повторно, граф стартует ровно с `session.current_step`.
```

- [ ] **Шаг 2: Поправить устаревшую перекрёстную ссылку**

Найти пункт 6 в `## Известные несостыковки, найденные при разборе`:

```
6. `progress_file_path` (`repo-initialization-progress.yaml`) формируется как строка один раз при старте
   workflow, но ни одна нода/сервис его не создаёт и не пишет — см. отдельный раздел
   «Compatibility-поле `progress_file_path`» выше.
```

Заменить на:

```
6. ~~`progress_file_path` не создаётся и не пишется~~ — исправлено: `_drive_graph_stream()` пишет
   YAML-снепшот на каждый шаг, а `resume_init_arch_from_snapshot` умеет по нему восстановить
   workflow на другой машине — см. раздел «Progress-снепшот `progress_file_path` и восстановление
   на другой машине» выше.
```

- [ ] **Шаг 3: Проверить, не осталось ли других устаревших упоминаний**

Команда: `grep -rn "progress_file_path" arch-docs/docs/`

Убедиться, что все оставшиеся упоминания либо соответствуют новому поведению, либо не содержат утверждения «никогда не пишется» (например, перечисление шагов в `init.md` просто называет поле, поведенческих утверждений не делает — не трогать).

- [ ] **Шаг 4: Коммит**

```bash
git add arch-docs/docs/workflows/init-graph-reference.md
git commit -m "docs(arch-docs): описать progress-снепшот и восстановление workflow на другой машине"
```

---

## Самопроверка

**Покрытие спецификации:**
- «хранить состояние в YAML, чтобы можно было хранить промежуточный результат в гит» → Задачи 1–3 (снепшот пишется в `arch_repo_dir`, который CLI-агент уже коммитит вместе с остальными knowledge-артефактами).
- «добавим функционал восстановления на другой машине и продолжение работы» → Задачи 4–6: `run_workflow(..., as_node=...)` сидирует checkpoint, `resume_init_arch_workflow_from_snapshot` строит новый `WorkflowRecord`/`InitArchState` из YAML и планирует продолжение, MCP-инструмент даёт внешний вход в этот флоу.
- «БД остаётся источником истины во время активного запуска» → сохранено: `workflow_runs`, `persist_workflow_record`, checkpointer, ретраи и interrupt-логика не менялись; запись снепшота и сидирование — чисто аддитивные, best-effort/явно контролируемые операции.

**Проверка на плейсхолдеры:** TBD/TODO нет, в каждом шаге — полный код, в каждом тесте — реальные проверки.

**Согласованность типов:** `write_snapshot_file(state: typing.Mapping[str, typing.Any])` (Задача 2) соответствует тому, как его вызывает Задача 3 (`write_snapshot_file(state_snapshot.values)`, где `.values` — обычный `dict`). `run_workflow(record, initial_state, *, as_node=None)` (Задача 4) — сигнатура, которую Задача 5 использует как `run_workflow(record, initial_state, as_node=as_node)`. `resume_init_arch_workflow_from_snapshot` (Задача 5) — та же сигнатура, что вызывает MCP-инструмент в Задаче 6. `WorkflowSnapshot`/`dump_snapshot_yaml`/`parse_snapshot_yaml` (Задача 1) используются с одинаковыми именами и сигнатурами во всех задачах, где встречаются.
