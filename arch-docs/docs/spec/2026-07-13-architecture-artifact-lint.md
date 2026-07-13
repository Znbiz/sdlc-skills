# План внедрения: schema-driven валидация артефактов architecture/*

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ SUB-SKILL: используй superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans для выполнения плана задача за задачей. Шаги отмечаются чекбоксами (`- [ ]`).

**Цель:** Заменить мёртвые инструкции `analysis_guard.py validate-contracts`/`validate-commits`, на которые сейчас ссылаются промпты worker'ов `init_arch` (но которых нет в сервисе `arch-docs`), на реальную, автоматическую, закодированную валидацию артефактов `architecture/*` — по тому же паттерну, который `knowledge_runtime.py` уже использует для слоя `wiki/`. Покрыть все 23 шаблона из `knowledge_base/` явным решением: либо новой проверкой, либо переиспользованием уже существующей, либо документированным обоснованным пропуском (см. таблицу покрытия ниже).

**Архитектура:** Добавить новый модуль `app/workflows/init_arch/architecture_lint.py`, который зеркалит существующий паттерн `run_knowledge_lint` из `knowledge_runtime.py`: чистые функции, читающие файлы внутри `arch_repo_dir` и возвращающие `list[str]` с issues в формате `ERROR:`. Подключить его к существующему вызову `run_knowledge_lint()`, чтобы он выполнялся автоматически на шаге workflow `run_knowledge_lint` (`StepId.RUN_KNOWLEDGE_LINT`) — том же quality gate, который уже блокирует переход к `validate_final` при наличии `ERROR:`.

## Таблица покрытия всех 23 шаблонов

| Шаблон в `knowledge_base/` | Целевой артефакт | Решение в этом плане |
| --- | --- | --- |
| `architecture/hld-template.md` | `architecture/hld.md` | Новая проверка обязательных секций (Задача 2) |
| `architecture/security-template.md` | `architecture/security.md` | Новая проверка обязательных секций (Задача 2) |
| `architecture/risks-template.md` | `architecture/risks.md` | Новая проверка обязательных секций (Задача 2) |
| `architecture/tech-stack-template.md` | `architecture/tech-stack.md` | Новая проверка обязательных секций (Задача 2) |
| `architecture/roles-and-permissions-template.md` | `architecture/roles-and-permissions.md` | Новая проверка обязательных секций (Задача 2) |
| `architecture/domain-entities-template.md` | `architecture/domain-entities.md` | Новая проверка обязательных секций (Задача 2) |
| `architecture/integrations-overview-template.md` | `architecture/integrations-overview.md` | Новая проверка обязательных секций (Задача 2) |
| `architecture/constraints-template.md` | `architecture/constraints.md` | Новая проверка обязательных секций (Задача 2) |
| `architecture/requirements-template.md` | `architecture/requirements.md` | Новая проверка обязательных секций (Задача 2) |
| `AGENTS-template.md` | `AGENTS.md` | Новая проверка секций, только если файл уже существует — он создаётся позже в workflow, чем `run_knowledge_lint` (Задача 3) |
| `architecture/integration-template.md` | `architecture/integrations/<service>.md` (много файлов) | Новая проверка секций по каждому файлу в каталоге (Задача 4) |
| `feature-template.md` | `features/<name>.md` (много файлов) | Новая проверка секций по каждому файлу в каталоге (Задача 4) |
| `architecture/contract-template.yml` | `architecture/contracts/*-sync.yml` | Новая структурная OpenAPI-проверка (Задача 5) |
| `architecture/async-contract-template.yml` | `architecture/contracts/*-async.yml` | Новая полноценная валидация по вендоренной официальной JSON Schema AsyncAPI 2.6.0 через `jsonschema` (Задача 5) |
| `architecture/storage-template.yml` | `architecture/storage/*.yml` | Новая минимальная схема-проверка (Задача 6) |
| `architecture/landscape-template.yaml` | `architecture/landscape.yaml` | Уже используется в проверке commit-консистентности (Задача 7); отдельной проверки структуры не требуется — `entities.services` и так парсится и валидируется там |
| `architecture/repo-structure-map-template.yml` | `architecture/structure/<repo>.yml` | Уже используется в проверке commit-консистентности (Задача 7) |
| `architecture/glossary-template.md` | `glossary.md` | Не требует новой проверки — шаблон уже используется при bootstrap (`knowledge.py:209`), а структуры сверх заголовка `# Глоссарий` шаблон не определяет |
| `architecture/support-repositories-template.md` | `architecture/support-repositories.md` | Шаблон **удалён** из `arch-docs` (нигде не читался кодом), структура инлайнена прямо в `checklist-repository-classification.md`. Артефакт `support-repositories.md` остаётся рабочей концепцией — фиксированных секций для отдельной lint-проверки нет (только повторяющиеся per-repo подзаголовки), см. Предварительные правки ниже |
| `features-index-template.md` | `features-index.md` | Уже используется при bootstrap и уже полноценно линтуется `_lint_feature_index` в `knowledge_runtime.py` — не дублируем |
| `open-questions-template.md` | `open-questions.md` | Уже используется при bootstrap и уже полноценно линтуется `_lint_open_questions_with_graph` — не дублируем |
| `index-template.md` | `wiki/index.md` (bootstrap-заглушка) | Финальная версия после `analysis_guard compile`/`build_navigation_index` уже проверяется `INDEX_REQUIRED_SECTIONS` в `knowledge_runtime.py` — не дублируем |
| `knowledge-log-template.md` | `wiki/log.md` | Уже полноценно линтуется `_lint_knowledge_log` в `knowledge_runtime.py` — не дублируем |
| `CLAUDE-template.md` | `CLAUDE.md` | Шаблон **удалён** из `arch-docs` (нигде не читался кодом, а содержимое тривиально — одна строка `@AGENTS.md`), см. Предварительные правки ниже |
| `repo-initialization-progress-template.yaml` | внешний progress-файл, не артефакт `arch_repo_dir` | Не применимо — этот файл не входит в архитектурный репозиторий и не проверяется knowledge lint'ом |

**Стек:** Python 3.14, pytest/pytest-asyncio, PyYAML и `openapi-spec-validator` (новые явные зависимости — PyYAML уже присутствует транзитивно через `langgraph`, план делает обе явными).

## Предварительные правки (уже выполнены до начала задач)

В ходе подготовки этого плана обнаружилось, что промпт worker'а (`prompts.py:139` инжектирует `SKILL.md` целиком + один reference-чеклист на шаг) и сами reference-чеклисты ссылались на файлы вида `assets/architecture/*-template.md` — путей, которых внутри контейнера worker'а физически нет (worker видит только `workspace_dir`/`arch_repo_dir`, каталог `shared_assets/` — часть файловой системы самого сервиса `arch-docs`, а не воркера). Это уже исправлено — правки не входят в задачи ниже, а являются их предпосылкой:

- В 10 файлах `arch-docs/app/workflows/shared_assets/init_arch/references/checklist-*.md` (`checklist-integrations-and-dependencies.md`, `checklist-roles-security-operability-risks.md`, `checklist-contracts-and-schemas.md`, `checklist-data-and-storage.md`, `checklist-domain-entities.md`, `checklist-repository-structure-mapping.md`, `checklist-repository-classification.md`, `checklist-features-and-index.md`, `checklist-tech-stack.md`) ссылки «по шаблону `assets/architecture/X-template.md`» заменены на инлайновую структуру артефакта прямо в тексте чеклиста — точный список обязательных секций/полей, совпадающий с тем, что валидирует `architecture_lint.py` из этого плана (единый источник структуры для промпта и для валидатора, пусть и продублированный текстуально).
- В `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md` убраны инструкции «используй шаблоны из `assets/`» и «используй `scripts/analysis_guard.py`» (оба пути недоступны воркеру) — заменены на описание того, что структура — в самих чеклистах, а прогресс workflow целиком отслеживает сервис через состояние сессии, не CLI.
- Удалены `arch-docs/app/workflows/shared_assets/knowledge_base/CLAUDE-template.md` и `arch-docs/app/workflows/shared_assets/knowledge_base/architecture/support-repositories-template.md` — ни один из них не читался кодом сервиса (`_load_asset` вызывается только для `features-index-template.md`, `architecture/glossary-template.md`, `open-questions-template.md`), а после инлайна структуры в чеклисты они стали полностью избыточны. Копии в `init-repo-arch-skill/assets/` и `update-repo-arch-skill/assets/` не тронуты — там у skill'а есть реальный доступ к файловой системе `assets/`.

## Глобальные ограничения

- Код и идентификаторы на английском; русский — только для комментариев/документации там, где это действительно нужно (по гайдлайнам pylines этого репозитория).
- Новая/изменённая логика должна поставляться с тестами, покрывающими дельту на уровне, близком к 100%, для нового модуля.
- Не изменять собственные `scripts/analysis_guard/*.py` в `init-repo-arch-skill` — это отдельный, независимо протестированный standalone skill; план переносит в `arch-docs` только *логику* валидации, не импортирует её (общего пакета между двумя репозиториями нет).
- Не изменять `init-repo-arch-skill/assets/`, `init-repo-arch-skill/references/`, `update-repo-arch-skill/assets/`, `update-repo-arch-skill/references/` — правки в «Предварительных правках» выше касаются только копий внутри `arch-docs`, у которых нет доступа к файловой системе `assets/` в контейнере worker'а. У отдельно устанавливаемых skill'ов эта проблема не воспроизводится.
- Вне скоупа (явно, не браться): переписывание CLI-мнемоник `domain --...`/`repo --...`/`timeline --...` по всему `SKILL.md` и checklist-референсам — они описывают операции, которые сервис уже выполняет иначе через `InitArchState`/`domain/operations.py`, и распутывание всех их — отдельная, более крупная задача на будущее.
- Каждая новая проверка обязательных секций требует существования файла (`ERROR: отсутствует ...`), кроме `AGENTS.md` — он по договорённости репозитория (`repository-layout.md`) создаётся позже в workflow, чем `run_knowledge_lint`, поэтому для него проверяются только секции, если файл уже есть.

---

## Структура файлов

- **Создать:** `arch-docs/app/workflows/init_arch/architecture_lint.py` — новый модуль со всеми проверками.
- **Создать:** `arch-docs/app/workflows/init_arch/schemas/asyncapi-2.6.0.json` — вендоренная официальная JSON Schema AsyncAPI 2.6.0.
- **Создать:** `arch-docs/tests/workflows/init_arch/test_architecture_lint.py` — юнит-тесты для нового модуля.
- **Изменить:** `arch-docs/app/workflows/init_arch/knowledge_runtime.py` — подключить `lint_architecture_artifacts` внутри `run_knowledge_lint()`.
- **Изменить:** `arch-docs/pyproject.toml` — добавить явные зависимости `pyyaml`, `openapi-spec-validator`, `jsonschema`.
- **Изменить:** `arch-docs/app/workflows/shared_assets/init_arch/references/checklist-architecture-artifact-updates.md` — заменить мёртвый bash-блок `analysis_guard.py validate-contracts`/`validate-commits` описанием нового автоматического gate.
- **Изменить:** `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md` — убрать два ложных утверждения о том, что `scripts/analysis_guard.py` — обязательный механизм progress-guard.
- **Изменить:** `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/landscape.yaml`, `.../security.md`, `.../risks.md`, `.../tech-stack.md`, `.../roles-and-permissions.md`, `.../integrations-overview.md`, `.../requirements.md`, `.../integrations/gateway-service.md`, `.../storage/gateway-service.yml` — привести к актуальным схемам/секциям.
- **Создать:** `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/structure/gateway-service.yml`, `.../architecture/domain-entities.md`, `.../architecture/constraints.md` — новые файлы фикстуры.
- **Изменить:** `init-repo-arch-skill/tests/fixtures/valid_arch_repo/features/0001-user-authentication.md` — добавить недостающие обязательные секции.

Эта директория фикстуры общая: `arch-docs/tests/workflows/init_arch/test_knowledge.py` читает её по абсолютному пути, а `init-repo-arch-skill/tests/test_analysis_guard_knowledge.py` копирует её через `FIXTURES_ROOT`. Оба test suite должны проходить после правки фикстуры.

---

### Задача 1: Добавить зависимости PyYAML и openapi-spec-validator

**Файлы:**
- Изменить: `arch-docs/pyproject.toml:5-22`

**Интерфейсы:**
- Производит: `import yaml`, `from openapi_spec_validator import validate` и `import jsonschema` становятся объявленными, безопасными импортами для любого модуля в `arch-docs/app`.

- [x] **Шаг 1: Добавить зависимости**

В `arch-docs/pyproject.toml`, внутри списка `dependencies = [...]` (начинается со строки 5), добавить новые строки после `"asyncpg>=0.29.0",`:

```toml
    "asyncpg>=0.29.0",
    "pyyaml>=6.0.0",
    "openapi-spec-validator>=0.7.0",
    "jsonschema>=4.0.0",
```

`openapi-spec-validator` даёт полноценную JSON-schema валидацию OpenAPI 2.x/3.x/3.1 (та же спецификация, которую понимает Swagger UI/Editor) — версия 0.9.0 на момент написания плана, требование `>=0.7.0` фиксирует минимальную версию с текущим API `validate(spec_dict)` из `openapi_spec_validator.validation.exceptions.OpenAPISpecValidatorError`. `jsonschema` — движок, на котором построен сам `openapi-spec-validator` (приходит транзитивно уже сейчас, версия 4.25.1 на момент написания плана), объявляется явно, потому что Задача 5 использует его напрямую для валидации AsyncAPI-контрактов по вендоренной официальной схеме.

- [x] **Шаг 2: Синхронизировать окружение**

Выполнить: `cd arch-docs && uv sync` (или эквивалентную команду синхронизации lock-файла; если `uv` не подтверждён как инструмент, свериться с `arch-docs/README.md`; PyYAML 6.0.3 уже присутствует в `.venv` транзитивно).

Ожидается: команда завершается с кодом 0.

- [x] **Шаг 3: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/pyproject.toml arch-docs/uv.lock
git commit -m "chore(arch-docs): объявить pyyaml прямой зависимостью"
```

(Если `uv.lock` отсутствует или называется иначе, добавить в `git add` соответствующий файл — сначала проверить вывод `git status`.)

---

### Задача 2: `architecture_lint.py` — обязательные секции для 9 одиночных markdown-артефактов

**Файлы:**
- Создать: `arch-docs/app/workflows/init_arch/architecture_lint.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`

**Интерфейсы:**
- Производит: `ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS: dict[str, tuple[str, ...]]`, `lint_architecture_artifacts(arch_repo_path: Path) -> list[str]`, `_lint_required_sections(arch_repo_path: Path, relative_path: str, required_sections: tuple[str, ...]) -> list[str]`.
- Потребляет: ничего из других задач пока (самодостаточна).

- [ ] **Шаг 1: Написать падающие тесты**

Создать `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`:

```python
from __future__ import annotations

from pathlib import Path

from app.workflows.init_arch import architecture_lint


def _write(tmp_path: Path, relative_path: str, body: str) -> Path:
    target_path = tmp_path / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(body, encoding="utf-8")
    return target_path


def test_lint_required_sections_reports_missing_file(tmp_path: Path) -> None:
    issues = architecture_lint._lint_required_sections(tmp_path, "architecture/hld.md", ("## X",))

    assert issues == ["ERROR: отсутствует architecture/hld.md"]


def test_lint_required_sections_reports_each_missing_heading(tmp_path: Path) -> None:
    _write(tmp_path, "architecture/hld.md", "# HLD\n\n## Обзор текущей архитектуры\n\nтекст\n")

    issues = architecture_lint._lint_required_sections(
        tmp_path, "architecture/hld.md", architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS["architecture/hld.md"]
    )

    assert "ERROR: architecture/hld.md не содержит обязательную секцию `## Контекстная диаграмма`" in issues
    assert "ERROR: architecture/hld.md не содержит обязательную секцию `## Обзор текущей архитектуры`" not in issues


def test_lint_required_sections_passes_when_all_present(tmp_path: Path) -> None:
    required_sections = architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS["architecture/risks.md"]
    body = "# Риски\n\n" + "\n\n".join(f"{section}\n\nтекст" for section in required_sections)
    _write(tmp_path, "architecture/risks.md", body)

    issues = architecture_lint._lint_required_sections(tmp_path, "architecture/risks.md", required_sections)

    assert issues == []


def test_lint_architecture_artifacts_reports_all_nine_missing_files(tmp_path: Path) -> None:
    issues = architecture_lint.lint_architecture_artifacts(tmp_path)

    for relative_path in architecture_lint.ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS:
        assert f"ERROR: отсутствует {relative_path}" in issues
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: `ModuleNotFoundError: No module named 'app.workflows.init_arch.architecture_lint'`.

- [ ] **Шаг 3: Написать минимальную реализацию**

Создать `arch-docs/app/workflows/init_arch/architecture_lint.py`:

```python
"""Structural and cross-artifact validation for architecture/* knowledge artifacts.

Mirrors the lint pattern in knowledge_runtime.py, but targets architecture/*
instead of the wiki layer. This is where the "Автоматические проверки" promised
in checklist-architecture-artifact-updates.md are actually enforced — the
worker prompt used to tell the agent to shell out to a CLI script
(scripts/analysis_guard.py) that does not exist inside this service.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS: Final[dict[str, tuple[str, ...]]] = {
    "architecture/hld.md": (
        "## Обзор текущей архитектуры",
        "## Контекстная диаграмма",
        "## Компоненты",
        "## Основные потоки",
        "## Интеграции",
        "## Риски и пробелы",
        "## Примечания по достоверности",
        "## Трассировка источников по разделам",
    ),
    "architecture/security.md": (
        "## Аутентификация пользователей и внешних клиентов",
        "## Межсервисное доверие",
        "## Границы доверия",
        "## Чувствительные данные",
        "## Примечания по достоверности",
        "## Закрытые вопросы",
    ),
    "architecture/risks.md": ("## Категории",),
    "architecture/tech-stack.md": ("## Правила заполнения", "## Таблица", "## Примечания"),
    "architecture/roles-and-permissions.md": ("## Роли", "## Матрица доступа к функционалу"),
    "architecture/domain-entities.md": ("## Расхождения и открытые вопросы", "## Источники подтверждения"),
    "architecture/integrations-overview.md": (
        "## Границы описания",
        "## Карта интеграций",
        "## Разрез по направлению",
        "## Основные потоки данных",
        "## Аутентификация и границы доверия",
        "## Примечания по надёжности",
        "## Наблюдаемость",
        "## Пробелы и открытые вопросы",
    ),
    "architecture/constraints.md": ("## Подтвержденные ограничения", "## Выведенные ограничения"),
    "architecture/requirements.md": (
        "## Наблюдаемые функциональные требования",
        "## Наблюдаемые или выведенные нефункциональные требования",
        "## Примечания по достоверности",
    ),
}


def lint_architecture_artifacts(arch_repo_path: Path) -> list[str]:
    issues: list[str] = []
    for relative_path, required_sections in ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS.items():
        issues.extend(_lint_required_sections(arch_repo_path, relative_path, required_sections))
    return issues


def _lint_required_sections(
    arch_repo_path: Path,
    relative_path: str,
    required_sections: tuple[str, ...],
) -> list[str]:
    artifact_path = arch_repo_path / relative_path
    if not artifact_path.exists():
        return [f"ERROR: отсутствует {relative_path}"]

    content = artifact_path.read_text(encoding="utf-8")
    return [
        f"ERROR: {relative_path} не содержит обязательную секцию `{section}`"
        for section in required_sections
        if section not in content
    ]
```

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: `4 passed`

- [ ] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): добавить проверку обязательных секций для 9 architecture/*.md артефактов"
```

---

### Задача 3: `architecture_lint.py` — обязательные секции `AGENTS.md` (только если файл существует)

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/architecture_lint.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`

**Интерфейсы:**
- Производит: `AGENTS_REQUIRED_SECTIONS: tuple[str, ...]`, `_lint_agents_md(arch_repo_path: Path) -> list[str]`, включённую в `lint_architecture_artifacts`.

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в конец `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`:

```python
def test_lint_agents_md_skips_when_file_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_agents_md(tmp_path)

    assert issues == []


def test_lint_agents_md_reports_missing_sections_when_present(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "# AGENTS.md\n\n## Что читать первым\n\nтекст\n")

    issues = architecture_lint._lint_agents_md(tmp_path)

    assert "ERROR: AGENTS.md не содержит обязательную секцию `## Source of Truth`" in issues
    assert "ERROR: AGENTS.md не содержит обязательную секцию `## Что читать первым`" not in issues


def test_lint_agents_md_passes_when_all_sections_present(tmp_path: Path) -> None:
    body = "# AGENTS.md\n\n" + "\n\n".join(
        f"{section}\n\nтекст" for section in architecture_lint.AGENTS_REQUIRED_SECTIONS
    )
    _write(tmp_path, "AGENTS.md", body)

    issues = architecture_lint._lint_agents_md(tmp_path)

    assert issues == []
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_agents_md`
Ожидается: падение с `AttributeError`.

- [ ] **Шаг 3: Написать минимальную реализацию**

Обновить `lint_architecture_artifacts` в `arch-docs/app/workflows/init_arch/architecture_lint.py`:

```python
def lint_architecture_artifacts(arch_repo_path: Path) -> list[str]:
    issues: list[str] = []
    for relative_path, required_sections in ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS.items():
        issues.extend(_lint_required_sections(arch_repo_path, relative_path, required_sections))
    issues.extend(_lint_agents_md(arch_repo_path))
    return issues
```

Добавить в конец файла:

```python
AGENTS_REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Что читать первым",
    "## Source of Truth",
    "## Структура репозитория",
    "## Operations",
    "## Правила трассировки и gaps",
    "## С чего начинать по типу задачи",
    "## Текущие сервисы",
    "## Как добавлять изменения",
)


def _lint_agents_md(arch_repo_path: Path) -> list[str]:
    agents_path = arch_repo_path / "AGENTS.md"
    if not agents_path.exists():
        return []

    content = agents_path.read_text(encoding="utf-8")
    return [
        f"ERROR: AGENTS.md не содержит обязательную секцию `{section}`"
        for section in AGENTS_REQUIRED_SECTIONS
        if section not in content
    ]
```

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: все тесты проходят.

- [ ] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): добавить опциональную проверку секций AGENTS.md"
```

---

### Задача 4: `architecture_lint.py` — обязательные секции для файлов в `integrations/` и `features/`

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/architecture_lint.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`

**Интерфейсы:**
- Производит: `INTEGRATION_REQUIRED_SECTIONS`, `FEATURE_REQUIRED_SECTIONS`, `_lint_directory_documents(arch_repo_path: Path, relative_dir: str, required_sections: tuple[str, ...]) -> list[str]`, включённую в `lint_architecture_artifacts` дважды.

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в конец `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`:

```python
def test_lint_directory_documents_skips_when_directory_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_directory_documents(tmp_path, "features", ("## X",))

    assert issues == []


def test_lint_directory_documents_reports_missing_sections_per_file(tmp_path: Path) -> None:
    _write(tmp_path, "features/0001-auth.md", "# Фича\n\n## Метаданные\n\nтекст\n")

    issues = architecture_lint._lint_directory_documents(tmp_path, "features", architecture_lint.FEATURE_REQUIRED_SECTIONS)

    assert "ERROR: features/0001-auth.md не содержит обязательную секцию `## Бизнес-возможность`" in issues


def test_lint_directory_documents_passes_when_all_sections_present(tmp_path: Path) -> None:
    body = "# Интеграция\n\n" + "\n\n".join(
        f"{section}\n\nтекст" for section in architecture_lint.INTEGRATION_REQUIRED_SECTIONS
    )
    _write(tmp_path, "architecture/integrations/gateway-service.md", body)

    issues = architecture_lint._lint_directory_documents(
        tmp_path, "architecture/integrations", architecture_lint.INTEGRATION_REQUIRED_SECTIONS
    )

    assert issues == []
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_directory_documents`
Ожидается: падение с `AttributeError`.

- [ ] **Шаг 3: Написать минимальную реализацию**

Обновить `lint_architecture_artifacts`:

```python
def lint_architecture_artifacts(arch_repo_path: Path) -> list[str]:
    issues: list[str] = []
    for relative_path, required_sections in ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS.items():
        issues.extend(_lint_required_sections(arch_repo_path, relative_path, required_sections))
    issues.extend(_lint_agents_md(arch_repo_path))
    issues.extend(_lint_directory_documents(arch_repo_path, "architecture/integrations", INTEGRATION_REQUIRED_SECTIONS))
    issues.extend(_lint_directory_documents(arch_repo_path, "features", FEATURE_REQUIRED_SECTIONS))
    return issues
```

Добавить в конец файла:

```python
INTEGRATION_REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Краткое описание сервиса",
    "## Входящие интеграции",
    "## Исходящие интеграции",
    "## Сводка по данным и границам доверия",
    "## Итоговые выводы",
    "## Закрытые вопросы",
    "## Трассировка источников по разделам",
)

FEATURE_REQUIRED_SECTIONS: Final[tuple[str, ...]] = (
    "## Метаданные",
    "## Бизнес-возможность",
    "## Текущее поведение",
    "## Функциональные правила",
    "## Основной поток",
    "## Трассировка реализации",
    "## Примечания по достоверности",
    "## Трассировка источников по разделам",
)


def _lint_directory_documents(
    arch_repo_path: Path,
    relative_dir: str,
    required_sections: tuple[str, ...],
) -> list[str]:
    directory = arch_repo_path / relative_dir
    if not directory.exists():
        return []

    issues: list[str] = []
    for markdown_path in sorted(directory.glob("*.md")):
        label = markdown_path.relative_to(arch_repo_path).as_posix()
        content = markdown_path.read_text(encoding="utf-8")
        issues.extend(
            f"ERROR: {label} не содержит обязательную секцию `{section}`"
            for section in required_sections
            if section not in content
        )
    return issues
```

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: все тесты проходят.

- [ ] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): добавить проверку обязательных секций для integrations/ и features/"
```

---

### Задача 5: `architecture_lint.py` — полноценная валидация контрактов: OpenAPI через `openapi-spec-validator`, AsyncAPI через вендоренную JSON Schema

**Файлы:**
- Создать: `arch-docs/app/workflows/init_arch/schemas/asyncapi-2.6.0.json` (вендоренный бинарный ассет — официальная схема, не пишется вручную)
- Изменить: `arch-docs/app/workflows/init_arch/architecture_lint.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`

**Интерфейсы:**
- Производит: `_lint_contracts(arch_repo_path: Path) -> list[str]`, включённую в `lint_architecture_artifacts`.

Для `*-sync.yml`/OpenAPI используется `openapi_spec_validator.validate()` — та же спецификация, по которой валидирует Swagger UI/Editor, так что документ, прошедший эту проверку, гарантированно можно открыть в Swagger.

Для `*-async.yml`/AsyncAPI полноценного Python-пакета уровня `openapi-spec-validator` не существует (пакет `asyncapi` на PyPI — это фреймворк для генерации AsyncAPI-документации из consumer-кода, а не валидатор произвольного YAML/JSON-документа; проверено установкой в изолированное окружение). Поэтому план вендорит официальную bundled JSON Schema AsyncAPI 2.6.0 (публикуется в `github.com/asyncapi/spec-json-schemas`, единый файл без внешних `$ref`, ~130 КБ, 3228 строк) и валидирует через `jsonschema.validate()` — тот же движок, на котором построен сам `openapi-spec-validator`. Это полноценная JSON-schema валидация, а не облегчённая структурная проверка — прогнано напрямую при подготовке плана: минимальный документ без `channels` даёт `'channels' is a required property`, корректный документ проходит без ошибок.

- [ ] **Шаг 1: Вендорить официальную JSON Schema AsyncAPI 2.6.0**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc/arch-docs
mkdir -p app/workflows/init_arch/schemas
curl -sL "https://raw.githubusercontent.com/asyncapi/spec-json-schemas/master/schemas/2.6.0.json" \
  -o app/workflows/init_arch/schemas/asyncapi-2.6.0.json
shasum -a 256 app/workflows/init_arch/schemas/asyncapi-2.6.0.json
```

Ожидается: `4b0bfe579e3c98a1da14db72bbd22a446ae23d5ae347ec7873a4cb488e446583  app/workflows/init_arch/schemas/asyncapi-2.6.0.json` (хэш вычислен и зафиксирован при подготовке этого плана — если он не совпадает, upstream-файл изменился, нужно свериться с `asyncapi/spec-json-schemas` вручную перед тем, как продолжать).

- [ ] **Шаг 2: Написать падающие тесты**

Добавить в конец `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`:

```python
def _write_contract(tmp_path: Path, name: str, body: str) -> Path:
    return _write(tmp_path, f"architecture/contracts/{name}", body)


def test_lint_contracts_skips_when_directory_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_contracts(tmp_path)

    assert issues == []


def test_lint_contracts_reports_invalid_yaml(tmp_path: Path) -> None:
    _write_contract(tmp_path, "broken-sync.yml", "openapi: [unclosed\n")

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert issues[0].startswith("ERROR: architecture/contracts/broken-sync.yml невалидный YAML:")


def test_lint_contracts_reports_missing_openapi_or_asyncapi_key(tmp_path: Path) -> None:
    _write_contract(tmp_path, "unknown-sync.yml", "service: gateway-service\n")

    issues = architecture_lint._lint_contracts(tmp_path)

    assert issues == [
        "ERROR: architecture/contracts/unknown-sync.yml не является OpenAPI/AsyncAPI контрактом: "
        "отсутствует ключ верхнего уровня `openapi` или `asyncapi`"
    ]


def test_lint_contracts_reports_openapi_missing_title(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "bad-title-sync.yml",
        "openapi: 3.0.3\ninfo:\n  version: '1.0.0'\npaths:\n  /ping:\n    get:\n      responses:\n        \"200\":\n          description: ok\n",
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert issues[0].startswith(
        "ERROR: architecture/contracts/bad-title-sync.yml не проходит валидацию openapi-spec-validator:"
    )
    assert "title" in issues[0]


def test_lint_contracts_reports_openapi_missing_responses(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "bad-responses-sync.yml",
        "openapi: 3.0.3\ninfo:\n  title: API\n  version: '1.0.0'\npaths:\n  /ping:\n    get:\n      summary: ping\n",
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert "responses" in issues[0]


def test_lint_contracts_passes_valid_openapi(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "good-sync.yml",
        (
            "openapi: 3.0.3\n"
            "info:\n"
            "  title: API\n"
            "  version: '1.0.0'\n"
            "paths:\n"
            "  /ping:\n"
            "    get:\n"
            "      responses:\n"
            "        \"200\":\n"
            "          description: ok\n"
        ),
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert issues == []


def test_lint_contracts_reports_asyncapi_missing_channels(tmp_path: Path) -> None:
    _write_contract(tmp_path, "events-async.yml", "asyncapi: 2.6.0\ninfo:\n  title: Events\n  version: '1.0.0'\n")

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert issues[0].startswith(
        "ERROR: architecture/contracts/events-async.yml не проходит валидацию AsyncAPI 2.6.0 JSON Schema:"
    )
    assert "channels" in issues[0]


def test_lint_contracts_reports_asyncapi_missing_info_version(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "events-async.yml",
        "asyncapi: 2.6.0\ninfo:\n  title: Events\nchannels:\n  user.created:\n    description: x\n",
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert len(issues) == 1
    assert "version" in issues[0]


def test_lint_contracts_passes_valid_asyncapi(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        "events-async.yml",
        "asyncapi: 2.6.0\ninfo:\n  title: Events\n  version: '1.0.0'\nchannels:\n  user.created:\n    description: x\n",
    )

    issues = architecture_lint._lint_contracts(tmp_path)

    assert issues == []
```

- [ ] **Шаг 3: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_contracts`
Ожидается: падение с `AttributeError`.

- [ ] **Шаг 4: Написать минимальную реализацию**

В `arch-docs/app/workflows/init_arch/architecture_lint.py` добавить импорты:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema
import yaml
from openapi_spec_validator import validate as validate_openapi
from openapi_spec_validator.validation.exceptions import OpenAPISpecValidatorError
```

Обновить `lint_architecture_artifacts`:

```python
def lint_architecture_artifacts(arch_repo_path: Path) -> list[str]:
    issues: list[str] = []
    for relative_path, required_sections in ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS.items():
        issues.extend(_lint_required_sections(arch_repo_path, relative_path, required_sections))
    issues.extend(_lint_agents_md(arch_repo_path))
    issues.extend(_lint_directory_documents(arch_repo_path, "architecture/integrations", INTEGRATION_REQUIRED_SECTIONS))
    issues.extend(_lint_directory_documents(arch_repo_path, "features", FEATURE_REQUIRED_SECTIONS))
    issues.extend(_lint_contracts(arch_repo_path))
    return issues
```

Добавить в конец файла:

```python
_ASYNCAPI_SCHEMA_PATH: Final[Path] = Path(__file__).parent / "schemas" / "asyncapi-2.6.0.json"
_asyncapi_schema_cache: dict[str, Any] | None = None


def _get_asyncapi_schema() -> dict[str, Any]:
    global _asyncapi_schema_cache  # noqa: PLW0603
    if _asyncapi_schema_cache is None:
        _asyncapi_schema_cache = json.loads(_ASYNCAPI_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _asyncapi_schema_cache


def _lint_contracts(arch_repo_path: Path) -> list[str]:
    contracts_dir = arch_repo_path / "architecture" / "contracts"
    if not contracts_dir.exists():
        return []

    issues: list[str] = []
    contract_paths = sorted(contracts_dir.glob("*.yml")) + sorted(contracts_dir.glob("*.yaml"))
    for contract_path in contract_paths:
        issues.extend(_lint_single_contract(contract_path, arch_repo_path))
    return issues


def _lint_single_contract(contract_path: Path, arch_repo_path: Path) -> list[str]:
    label = contract_path.relative_to(arch_repo_path).as_posix()
    try:
        document = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"ERROR: {label} невалидный YAML: {error}"]

    if not isinstance(document, dict):
        return [f"ERROR: {label} невалидный контракт: ожидается mapping верхнего уровня"]

    if "openapi" in document:
        return _lint_openapi_contract(document, label)
    if "asyncapi" in document:
        return _lint_asyncapi_contract(document, label)
    return [f"ERROR: {label} не является OpenAPI/AsyncAPI контрактом: отсутствует ключ верхнего уровня `openapi` или `asyncapi`"]


def _lint_openapi_contract(document: dict[str, Any], label: str) -> list[str]:
    try:
        validate_openapi(document)
    except OpenAPISpecValidatorError as error:
        first_line = str(error).strip().splitlines()[0]
        return [f"ERROR: {label} не проходит валидацию openapi-spec-validator: {first_line}"]
    return []


def _lint_asyncapi_contract(document: dict[str, Any], label: str) -> list[str]:
    try:
        jsonschema.validate(document, _get_asyncapi_schema())
    except jsonschema.exceptions.ValidationError as error:
        first_line = str(error).strip().splitlines()[0]
        return [f"ERROR: {label} не проходит валидацию AsyncAPI 2.6.0 JSON Schema: {first_line}"]
    return []
```

`validate_openapi()` и `jsonschema.validate()` сами проверяют наличие и корректность `info.title`/`info.version`, структуру `paths`/`channels` и вложенных объектов по официальным JSON-schema обеих спецификаций — отдельные ручные проверки этих полей больше не нужны, они были бы дублированием с риском разойтись с реальной спецификацией.

- [ ] **Шаг 5: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: все тесты проходят.

- [ ] **Шаг 6: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/app/workflows/init_arch/schemas/asyncapi-2.6.0.json arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): валидировать OpenAPI через openapi-spec-validator и AsyncAPI через вендоренную JSON Schema"
```

---

### Задача 6: `architecture_lint.py` — минимальная схема-проверка `storage/*.yml`

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/architecture_lint.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`

**Интерфейсы:**
- Производит: `_lint_storage(arch_repo_path: Path) -> list[str]`, включённую в `lint_architecture_artifacts`. По аналогии с `_lint_contracts`, проверяет только сигнатурные поля шаблона `storage-template.yml`: mapping верхнего уровня `storage` с непустым `storage.type`.

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в конец `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`:

```python
def _write_storage(tmp_path: Path, name: str, body: str) -> Path:
    return _write(tmp_path, f"architecture/storage/{name}", body)


def test_lint_storage_skips_when_directory_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_storage(tmp_path)

    assert issues == []


def test_lint_storage_reports_missing_top_level_key(tmp_path: Path) -> None:
    _write_storage(tmp_path, "gateway-service.yml", "service: gateway-service\n")

    issues = architecture_lint._lint_storage(tmp_path)

    assert issues == [
        "ERROR: architecture/storage/gateway-service.yml не содержит mapping верхнего уровня `storage`"
    ]


def test_lint_storage_reports_missing_type(tmp_path: Path) -> None:
    _write_storage(tmp_path, "gateway-service.yml", "storage:\n  id: gateway-tokens\n")

    issues = architecture_lint._lint_storage(tmp_path)

    assert issues == ["ERROR: architecture/storage/gateway-service.yml не содержит `storage.type`"]


def test_lint_storage_passes_valid_document(tmp_path: Path) -> None:
    _write_storage(tmp_path, "gateway-service.yml", "storage:\n  id: gateway-tokens\n  type: postgresql\n")

    issues = architecture_lint._lint_storage(tmp_path)

    assert issues == []
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_storage`
Ожидается: падение с `AttributeError`.

- [ ] **Шаг 3: Написать минимальную реализацию**

Обновить `lint_architecture_artifacts`:

```python
def lint_architecture_artifacts(arch_repo_path: Path) -> list[str]:
    issues: list[str] = []
    for relative_path, required_sections in ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS.items():
        issues.extend(_lint_required_sections(arch_repo_path, relative_path, required_sections))
    issues.extend(_lint_agents_md(arch_repo_path))
    issues.extend(_lint_directory_documents(arch_repo_path, "architecture/integrations", INTEGRATION_REQUIRED_SECTIONS))
    issues.extend(_lint_directory_documents(arch_repo_path, "features", FEATURE_REQUIRED_SECTIONS))
    issues.extend(_lint_contracts(arch_repo_path))
    issues.extend(_lint_storage(arch_repo_path))
    return issues
```

Добавить в конец файла:

```python
def _lint_storage(arch_repo_path: Path) -> list[str]:
    storage_dir = arch_repo_path / "architecture" / "storage"
    if not storage_dir.exists():
        return []

    issues: list[str] = []
    for storage_path in sorted(storage_dir.glob("*.yml")):
        label = storage_path.relative_to(arch_repo_path).as_posix()
        try:
            document = yaml.safe_load(storage_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            issues.append(f"ERROR: {label} невалидный YAML: {error}")
            continue

        storage_section = document.get("storage") if isinstance(document, dict) else None
        if not isinstance(storage_section, dict):
            issues.append(f"ERROR: {label} не содержит mapping верхнего уровня `storage`")
            continue
        if not storage_section.get("type"):
            issues.append(f"ERROR: {label} не содержит `storage.type`")
    return issues
```

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: все тесты проходят.

- [ ] **Шаг 5: Запустить ruff и исправить**

Выполнить: `cd arch-docs && .venv/bin/ruff check app/workflows/init_arch/architecture_lint.py tests/workflows/init_arch/test_architecture_lint.py --fix`
Ожидается: код возврата 0, либо только автоисправимые замечания. Если ruff отметит complexity/line-length в `architecture_lint.py`, добавить точечную запись `extend-per-file-ignores` в `pyproject.toml` по аналогии с `knowledge_runtime.py`, а не общий `# noqa`.

- [ ] **Шаг 6: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): добавить минимальную схема-проверку architecture/storage/*.yml"
```

---

### Задача 7: `architecture_lint.py` — согласованность commit между landscape и structure

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/architecture_lint.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`

**Интерфейсы:**
- Производит: `_lint_commit_consistency(arch_repo_path: Path) -> list[str]`, включённую в `lint_architecture_artifacts`. Прямой перенос логики из `init-repo-arch-skill/scripts/analysis_guard/commit_consistency.py::validate_commit_consistency`, упрощённый до прямого `yaml.safe_load` вместо JSON/ruby-фолбэков (PyYAML гарантирован задачей 1). Эта же функция закрывает покрытие `landscape-template.yaml` и `repo-structure-map-template.yml` из таблицы покрытия — оба файла парсятся и валидируются по сигнатурным полям (`entities.services`, `repo_structure_map.analyzed_commit`).

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в конец `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`:

```python
def _write_landscape(tmp_path: Path, body: str) -> Path:
    return _write(tmp_path, "architecture/landscape.yaml", body)


def _write_structure(tmp_path: Path, service_id: str, body: str) -> Path:
    return _write(tmp_path, f"architecture/structure/{service_id}.yml", body)


def test_lint_commit_consistency_skips_when_landscape_missing(tmp_path: Path) -> None:
    issues = architecture_lint._lint_commit_consistency(tmp_path)

    assert issues == []


def test_lint_commit_consistency_reports_missing_structure_file(tmp_path: Path) -> None:
    _write_landscape(
        tmp_path,
        "entities:\n  services:\n    - id: gateway-service\n      repository_state:\n        head_commit: abc123\n",
    )

    issues = architecture_lint._lint_commit_consistency(tmp_path)

    assert issues == [
        "ERROR: architecture/structure/gateway-service.yml не найден для сервиса `gateway-service` из landscape.yaml"
    ]


def test_lint_commit_consistency_reports_mismatch(tmp_path: Path) -> None:
    _write_landscape(
        tmp_path,
        "entities:\n  services:\n    - id: gateway-service\n      repository_state:\n        head_commit: abc123\n",
    )
    _write_structure(tmp_path, "gateway-service", "repo_structure_map:\n  analyzed_commit: def456\n")

    issues = architecture_lint._lint_commit_consistency(tmp_path)

    assert issues == [
        "ERROR: рассинхронизация commit между landscape.yaml (head_commit=`abc123`) и "
        "architecture/structure/gateway-service.yml (analyzed_commit=`def456`) для сервиса `gateway-service`"
    ]


def test_lint_commit_consistency_passes_when_commits_match(tmp_path: Path) -> None:
    _write_landscape(
        tmp_path,
        "entities:\n  services:\n    - id: gateway-service\n      repository_state:\n        head_commit: abc123\n",
    )
    _write_structure(tmp_path, "gateway-service", "repo_structure_map:\n  analyzed_commit: abc123\n")

    issues = architecture_lint._lint_commit_consistency(tmp_path)

    assert issues == []
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_commit_consistency`
Ожидается: падение с `AttributeError`.

- [ ] **Шаг 3: Написать минимальную реализацию**

Обновить `lint_architecture_artifacts`:

```python
def lint_architecture_artifacts(arch_repo_path: Path) -> list[str]:
    issues: list[str] = []
    for relative_path, required_sections in ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS.items():
        issues.extend(_lint_required_sections(arch_repo_path, relative_path, required_sections))
    issues.extend(_lint_agents_md(arch_repo_path))
    issues.extend(_lint_directory_documents(arch_repo_path, "architecture/integrations", INTEGRATION_REQUIRED_SECTIONS))
    issues.extend(_lint_directory_documents(arch_repo_path, "features", FEATURE_REQUIRED_SECTIONS))
    issues.extend(_lint_contracts(arch_repo_path))
    issues.extend(_lint_storage(arch_repo_path))
    issues.extend(_lint_commit_consistency(arch_repo_path))
    return issues
```

Добавить в конец файла:

```python
def _lint_commit_consistency(arch_repo_path: Path) -> list[str]:
    landscape_path = arch_repo_path / "architecture" / "landscape.yaml"
    if not landscape_path.exists():
        return []

    try:
        landscape = yaml.safe_load(landscape_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [f"ERROR: architecture/landscape.yaml невалидный YAML: {error}"]

    if not isinstance(landscape, dict):
        return ["ERROR: architecture/landscape.yaml невалидный формат: ожидается mapping верхнего уровня"]

    services = ((landscape.get("entities") or {}).get("services")) or []
    if not isinstance(services, list):
        return ["ERROR: architecture/landscape.yaml: entities.services должен быть списком"]

    issues: list[str] = []
    structure_dir = arch_repo_path / "architecture" / "structure"
    for service in services:
        if not isinstance(service, dict):
            continue
        service_id = service.get("id") or service.get("name")
        head_commit = ((service.get("repository_state") or {}).get("head_commit") or "").strip()
        if not service_id or not head_commit:
            continue

        structure_path = structure_dir / f"{service_id}.yml"
        if not structure_path.exists():
            issues.append(
                f"ERROR: architecture/structure/{service_id}.yml не найден для сервиса `{service_id}` из landscape.yaml"
            )
            continue

        try:
            structure_document = yaml.safe_load(structure_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            issues.append(f"ERROR: architecture/structure/{service_id}.yml невалидный YAML: {error}")
            continue

        analyzed_commit = ((structure_document or {}).get("repo_structure_map") or {}).get("analyzed_commit") or ""
        analyzed_commit = str(analyzed_commit).strip()
        if analyzed_commit and analyzed_commit != head_commit:
            issues.append(
                f"ERROR: рассинхронизация commit между landscape.yaml (head_commit=`{head_commit}`) и "
                f"architecture/structure/{service_id}.yml (analyzed_commit=`{analyzed_commit}`) "
                f"для сервиса `{service_id}`"
            )
    return issues
```

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: все тесты проходят (полный набор для модуля).

- [ ] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): добавить проверку согласованности commit между landscape.yaml и structure-картами"
```

---

### Задача 8: Подключить `lint_architecture_artifacts` к `run_knowledge_lint`

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/knowledge_runtime.py:393-451` (функция `run_knowledge_lint`)
- Тест: `arch-docs/tests/workflows/init_arch/test_knowledge_runtime.py`

**Интерфейсы:**
- Потребляет: `lint_architecture_artifacts(arch_repo_path: Path) -> list[str]` из `architecture_lint.py` (задачи 2-7).
- Производит: `run_knowledge_lint(arch_repo_path: Path) -> list[str]` теперь включает issues по architecture-артефактам (эту функцию уже вызывает `KnowledgeArtifactService.lint_knowledge` в `knowledge.py` на шаге `run_knowledge_lint` — там менять ничего не нужно).

- [ ] **Шаг 1: Написать падающий тест**

Добавить в конец `arch-docs/tests/workflows/init_arch/test_knowledge_runtime.py`:

```python
def test_run_knowledge_lint_includes_architecture_artifact_issues(tmp_path: Path) -> None:
    (tmp_path / "wiki" / "maps").mkdir(parents=True)
    (tmp_path / "features").mkdir()
    (tmp_path / "architecture").mkdir()

    issues = runtime.run_knowledge_lint(tmp_path)

    assert "ERROR: отсутствует architecture/hld.md" in issues
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_knowledge_runtime.py -v -k test_run_knowledge_lint_includes_architecture_artifact_issues`
Ожидается: FAIL.

- [ ] **Шаг 3: Подключить проверку**

В `arch-docs/app/workflows/init_arch/knowledge_runtime.py` добавить импорт рядом с началом файла (после `from typing import Final`, около строки 10):

```python
from app.workflows.init_arch.architecture_lint import lint_architecture_artifacts
```

Внутри `run_knowledge_lint` (начинается со строки 393) добавить строку прямо перед `return issues` (сейчас строка 451):

```python
    issues.extend(lint_architecture_artifacts(arch_repo_path))

    return issues
```

- [ ] **Шаг 4: Запустить тест и убедиться, что он проходит**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_knowledge_runtime.py -v -k test_run_knowledge_lint_includes_architecture_artifact_issues`
Ожидается: PASS

- [ ] **Шаг 5: Запустить полный knowledge test suite**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_knowledge_runtime.py tests/workflows/init_arch/test_knowledge.py -v`
Ожидается: тесты на базе фикстуры `valid_arch_repo` теперь FAIL с большим числом `ERROR:` (по всем 9 markdown-артефактам, integrations, features, storage, landscape/structure) — это ожидаемо, задача 9 чинит фикстуру. Зафиксировать полный список упавших issues, чтобы задача 9 могла проверить их закрытие один к одному.

- [ ] **Шаг 6: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/knowledge_runtime.py arch-docs/tests/workflows/init_arch/test_knowledge_runtime.py
git commit -m "feat(arch-docs): подключить lint_architecture_artifacts к run_knowledge_lint"
```

---

### Задача 9: Привести общую фикстуру в соответствие со всеми новыми проверками

**Файлы:**
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/landscape.yaml`
- Создать: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/structure/gateway-service.yml`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/contracts/gateway-service-sync.yml`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/hld.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/security.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/risks.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/tech-stack.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/roles-and-permissions.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/integrations-overview.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/requirements.md`
- Создать: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/domain-entities.md`
- Создать: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/constraints.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/integrations/gateway-service.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/features/0001-user-authentication.md`
- Изменить: `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/storage/gateway-service.yml`

**Интерфейсы:**
- Потребляет: все проверки из задач 2-7.
- Производит: фикстуру, которая даёт ноль issues уровня `ERROR:` от `run_knowledge_lint`, используемую обоими test suite — `arch-docs` и `init-repo-arch-skill`.

Эта фикстура старше текущих шаблонов почти по всем артефактам сразу — она никогда не была реально валидной относительно проверок, которые добавляют задачи 2-7, что и является тем пробелом, который закрывает план.

- [ ] **Шаг 1: Переписать `landscape.yaml`**

Полное содержимое `init-repo-arch-skill/tests/fixtures/valid_arch_repo/architecture/landscape.yaml`:

```yaml
system:
  name: ai-cli-gateway
  product: AI CLI Gateway Service
  owner: platform-team
  repository: https://github.com/znbiz/gateway-service

entities:
  services:
    - id: gateway-service
      name: gateway-service
      repository: https://github.com/znbiz/gateway-service
      description: Backend CLI gateway сервис
      technology: Python / FastAPI
      repository_state:
        main_branch: main
        head_commit: abc123
    - id: gateway-web
      name: gateway-web
      repository: https://github.com/znbiz/gateway-web
      description: Web-интерфейс логина CLI
      technology: TypeScript / Next.js
      repository_state:
        main_branch: main
        head_commit: def456

  storages: []
  external_systems: []

relationships: []
```

- [ ] **Шаг 2: Добавить `architecture/structure/gateway-service.yml`**

Полное содержимое нового файла:

```yaml
repo_structure_map:
  repository: gateway-service
  analyzed_commit: abc123
  built_at: "2026-07-03T00:00:00Z"
  assertion_type: наблюдаемый факт
  sources:
    - gateway-service/src/api/auth.py
  categories: {}
```

Примечание: у `gateway-web` намеренно нет соответствующего `architecture/structure/gateway-web.yml` — если это станет проблемой для нулевого числа `ERROR:` в smoke-тесте, добавить второй минимальный structure-файл для `gateway-web` с `analyzed_commit: def456` вместо удаления проверки.

- [ ] **Шаг 3: Переписать фикстуру контракта**

Полное содержимое `architecture/contracts/gateway-service-sync.yml` — проверено напрямую через `openapi_spec_validator.validate()` (см. Задачу 5), документ проходит валидацию без изменений:

```yaml
openapi: 3.0.3
info:
  title: API сервиса gateway-service
  version: "1.0.0"
  description: CLI-токен обмен

x-traceability:
  assertion_type: наблюдаемый факт
  sources:
    - gateway-service/openapi/auth.yaml

paths:
  /auth/token:
    post:
      summary: Получение CLI-токена
      operationId: createCliToken
      responses:
        "200":
          description: Токен выдан
```

- [ ] **Шаг 4: Дополнить `hld.md`**

Полное содержимое `architecture/hld.md`:

```markdown
---
title: "HLD"
type: hld
sources:
  - gateway-service/src/api/auth.py
  - gateway-web/src/pages/login.tsx
related:
  - features/0001-user-authentication.md
  - architecture/integrations/gateway-service.md
created: "2026-07-03"
updated: "2026-07-03"
confidence: high
domain: identity
repositories:
  - gateway-service
  - gateway-web
---

# HLD

## Источники

- `gateway-service/src/api/auth.py`
- `gateway-web/src/pages/login.tsx`

## Обзор текущей архитектуры

CLI Gateway состоит из backend-сервиса `gateway-service` и web-интерфейса логина `gateway-web`.

## Контекстная диаграмма

`gateway-web` обращается к `gateway-service` по HTTP для получения CLI-токена; собственных внешних зависимостей у `gateway-service` в этом прогоне не подтверждено.

## Компоненты

### gateway-service

Backend-сервис, выдаёт CLI-токен по `/auth/token` (см. `gateway-service/src/api/auth.py`).

### gateway-web

Web-интерфейс логина, вызывает `gateway-service` для обмена учётных данных на CLI-токен (см. `gateway-web/src/pages/login.tsx`).

## Основные потоки

1. Пользователь логинится через `gateway-web`.
2. `gateway-web` вызывает `gateway-service` `/auth/token`.
3. `gateway-service` возвращает CLI-токен.

## Интеграции

См. `architecture/integrations/gateway-service.md`.

## Риски и пробелы

См. `architecture/risks.md`.

## Примечания по достоверности

Все утверждения в этом разделе подтверждены кодом, перечисленным в frontmatter `sources`.

## Трассировка источников по разделам

| Раздел | Тип утверждения | Источники |
| --- | --- | --- |
| `Обзор текущей архитектуры` | `наблюдаемый факт` | `gateway-service/src/api/auth.py`, `gateway-web/src/pages/login.tsx` |
```

- [ ] **Шаг 5: Дополнить `security.md`**

Полное содержимое `architecture/security.md`:

```markdown
---
title: "Безопасность gateway"
type: security
sources:
  - gateway-service/src/api/auth.py
related:
  - architecture/hld.md
  - features/0001-user-authentication.md
created: "2026-07-03"
updated: "2026-07-03"
confidence: medium
domain: identity
repositories:
  - gateway-service
---

# Безопасность

## Источники

- `gateway-service/src/api/auth.py`

## Аутентификация пользователей и внешних клиентов

Пользователь логинится через `gateway-web`, получает CLI-токен от `gateway-service`.

## Межсервисное доверие

Прямого межсервисного доверия между `gateway-service` и внешними системами в этом прогоне не подтверждено.

## Границы доверия

CLI-токен передаётся в `Authorization` header и считается границей доверия между `gateway-web` и `gateway-service`.

## Чувствительные данные

CLI-токен и учётные данные пользователя — чувствительные данные, обрабатываемые `gateway-service/src/api/auth.py`.

## Примечания по достоверности

Rotation policy для токенов не найдена в коде — требует подтверждения.

## Закрытые вопросы

Нет.
```

- [ ] **Шаг 6: Дополнить `risks.md`**

Полное содержимое `architecture/risks.md`:

```markdown
---
title: "Риски gateway"
type: risk
sources:
  - gateway-service/src/api/auth.py
related:
  - architecture/security.md
created: "2026-07-03"
updated: "2026-07-03"
confidence: medium
domain: identity
repositories:
  - gateway-service
---

# Риски

## Источники

- `gateway-service/src/api/auth.py`

## Категории

- Риск: не найдено подтверждение rotation policy для токенов.
```

- [ ] **Шаг 7: Дополнить `tech-stack.md`**

Полное содержимое `architecture/tech-stack.md`:

```markdown
# Технологический стек

## Источники

- `gateway-service/pyproject.toml`
- `gateway-web/package.json`

## Правила заполнения

Каждая строка таблицы фиксирует сервис, зависимость, версию и источник подтверждения.

## Таблица

| Сервис | Зависимость | Версия | Источник |
| --- | --- | --- | --- |
| `gateway-service` | `Python` | `3.14` | `gateway-service/pyproject.toml` |
| `gateway-web` | `TypeScript` | `5.x` | `gateway-web/package.json` |

## Примечания

Backend: `Python`. Frontend: `TypeScript`.
```

- [ ] **Шаг 8: Дополнить `roles-and-permissions.md`**

Полное содержимое `architecture/roles-and-permissions.md`:

```markdown
# Роли И Матрица Функционала

## Источники

- `gateway-service/src/api/auth.py`

## Роли

- `operator` — получает CLI-токен и вызывает downstream API.

## Матрица доступа к функционалу

| Функционал | `operator` |
| --- | --- |
| Получение CLI-токена | да |
```

- [ ] **Шаг 9: Дополнить `integrations-overview.md`**

Полное содержимое `architecture/integrations-overview.md`:

```markdown
# Обзор интеграций

## Источники

- `gateway-service/src/api/auth.py`

## Границы описания

Описаны интеграции, подтверждённые в `gateway-service` и `gateway-web` в рамках текущего прогона.

## Карта интеграций

- `gateway-service` вызывает `identity-provider`.

## Разрез по направлению

### Входящие

- `gateway-web` -> `gateway-service`: получение CLI-токена.

### Исходящие

- `gateway-service` -> `identity-provider`: валидация учётных данных.

### Асинхронные

Не найдено.

## Основные потоки данных

CLI-токен передаётся от `gateway-service` к `gateway-web` синхронно по HTTP.

## Аутентификация и границы доверия

См. `architecture/security.md`.

## Примечания по надёжности

Retry/timeout policy не найдены в коде — требует подтверждения.

## Наблюдаемость

Логирование запросов авторизации подтверждено в `gateway-service/src/api/auth.py`.

## Пробелы и открытые вопросы

Нет.
```

- [ ] **Шаг 10: Дополнить `requirements.md`**

Полное содержимое `architecture/requirements.md`:

```markdown
---
title: "Требования gateway"
type: requirements
sources:
  - gateway-service/src/api/auth.py
related:
  - features/0001-user-authentication.md
created: "2026-07-03"
updated: "2026-07-03"
confidence: medium
domain: identity
repositories:
  - gateway-service
---

# Функциональные и нефункциональные требования

## Наблюдаемые функциональные требования

1. Пользователь может получить CLI-токен.

## Наблюдаемые или выведенные нефункциональные требования

Специфичные НФТ (доступность, производительность, надёжность) в коде не найдены — требует подтверждения.

## Примечания по достоверности

Функциональное требование подтверждено кодом `gateway-service/src/api/auth.py`.
```

- [ ] **Шаг 11: Создать `domain-entities.md`**

Полное содержимое нового файла `architecture/domain-entities.md`:

```markdown
# Ключевые бизнес-сущности

## Источники

- `gateway-service/src/api/auth.py`

## CliToken

### Поля

- `token` (string) — CLI-токен, выдаваемый после логина.

## Расхождения и открытые вопросы

Нет.

## Источники подтверждения

- `gateway-service/src/api/auth.py`
```

- [ ] **Шаг 12: Создать `constraints.md`**

Полное содержимое нового файла `architecture/constraints.md`:

```markdown
# Архитектурные ограничения

## Источники

- `gateway-service/src/api/auth.py`

## Подтвержденные ограничения

Нет подтверждённых ограничений в рамках текущего прогона.

## Выведенные ограничения

CLI-токен передаётся только по HTTPS в продакшне (выведено косвенно из `servers` в контракте `gateway-service-sync.yml`).
```

- [ ] **Шаг 13: Дополнить `integrations/gateway-service.md`**

Полное содержимое `architecture/integrations/gateway-service.md`:

```markdown
---
title: "Интеграции gateway-service"
type: integration
sources:
  - gateway-service/src/api/auth.py
related:
  - features/0001-user-authentication.md
  - architecture/hld.md
created: "2026-07-03"
updated: "2026-07-03"
confidence: high
domain: identity
repositories:
  - gateway-service
---

# Интеграции сервиса: gateway-service

## Краткое описание сервиса

- Сервис: `gateway-service`
- Основные источники:
  - `gateway-service/src/api/auth.py`

## Входящие интеграции

### `gateway-web->gateway-service`

`gateway-web` вызывает `gateway-service` для получения CLI-токена по `/auth/token`.

## Исходящие интеграции

### `gateway-service->identity-provider`

`gateway-service` валидирует учётные данные через `identity-provider`.

## Сводка по данным и границам доверия

CLI-токен и учётные данные пользователя пересекают границу доверия между `gateway-web` и `gateway-service`.

## Итоговые выводы

`gateway-service` — единственная точка выдачи CLI-токена в этом прогоне.

## Закрытые вопросы

Нет.

## Трассировка источников по разделам

| Раздел | Тип утверждения | Источники |
| --- | --- | --- |
| `Краткое описание сервиса` | `наблюдаемый факт` | `gateway-service/src/api/auth.py` |
```

- [ ] **Шаг 14: Дополнить `features/0001-user-authentication.md`**

Полное содержимое `features/0001-user-authentication.md`:

```markdown
---
title: "Аутентификация пользователя"
type: feature
sources:
  - gateway-service/src/api/auth.py
  - gateway-service/tests/integration/test_auth.py
related:
  - architecture/hld.md
  - architecture/integrations/gateway-service.md
created: "2026-07-03"
updated: "2026-07-03"
confidence: high
domain: identity
repositories:
  - gateway-service
  - gateway-web
---

# Фича: Аутентификация пользователя

## Метаданные

- Идентификатор фичи: `FEAT-0001`
- Тип утверждения по умолчанию: `наблюдаемый факт`
- Основные источники:
  - `gateway-service/src/api/auth.py`
  - `gateway-service/tests/integration/test_auth.py`

## Бизнес-возможность

Пользователь может получить CLI-токен для работы с downstream API через `gateway-web`.

## Текущее поведение

Gateway принимает credentials пользователя, выпускает CLI-токен и использует его для вызовов downstream API.

## Функциональные правила

1. CLI-токен выдаётся только после успешной проверки credentials.

## Основной поток

1. Пользователь вводит credentials в `gateway-web`.
2. `gateway-web` вызывает `gateway-service` `/auth/token`.
3. `gateway-service` возвращает CLI-токен.

## Трассировка реализации

### Точки входа

- `gateway-service/src/api/auth.py`

### Подтверждающие тесты

- `gateway-service/tests/integration/test_auth.py`

## Примечания по достоверности

Поведение подтверждено интеграционным тестом.

## Закрытые вопросы

- `Q-1` — подтверждение выдачи CLI-токена вынесено в этот feature-артефакт.

## Трассировка источников по разделам

| Раздел | Тип утверждения | Источники |
| --- | --- | --- |
| `Текущее поведение` | `наблюдаемый факт` | `gateway-service/src/api/auth.py`, `gateway-service/tests/integration/test_auth.py` |
```

- [ ] **Шаг 15: Переписать `storage/gateway-service.yml`**

Полное содержимое `architecture/storage/gateway-service.yml`:

```yaml
storage:
  id: gateway-tokens
  name: gateway_tokens
  type: postgresql
  description: Таблица активных CLI-токенов
  assertion_type: наблюдаемый факт
  sources:
    - gateway-service/migrations/001_init.sql

schemas:
  - name: public
    assertion_type: наблюдаемый факт
    sources:
      - gateway-service/migrations/001_init.sql
    tables:
      - name: gateway_tokens
        description: CLI-токены пользователей
        assertion_type: наблюдаемый факт
        sources:
          - gateway-service/migrations/001_init.sql
        columns: []
```

- [ ] **Шаг 16: Запустить knowledge test suite `arch-docs`**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_knowledge_runtime.py tests/workflows/init_arch/test_knowledge.py -v`
Ожидается: все тесты, упавшие на шаге 5 задачи 8, теперь проходят. Если smoke-тест всё ещё репортит `ERROR:` про отсутствующий structure-файл `gateway-web`, добавить второй structure-файл по примечанию из шага 2 и перезапустить.

- [ ] **Шаг 17: Запустить полный test suite `arch-docs`**

Выполнить: `cd arch-docs && .venv/bin/pytest -v`
Ожидается: все тесты проходят, посторонних регрессий нет.

- [ ] **Шаг 18: Запустить test suite `init-repo-arch-skill`**

Выполнить: `cd init-repo-arch-skill && python3 -m pytest tests/ -v` (свериться с `README.md`/CI-конфигом, если команда отличается).
Ожидается: все тесты проходят.

- [ ] **Шаг 19: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add init-repo-arch-skill/tests/fixtures/valid_arch_repo
git commit -m "test: обновить valid_arch_repo фикстуру под все проверки architecture_lint"
```

---

### Задача 10: Заменить мёртвые команды `analysis_guard.py` в checklist-референсе

**Файлы:**
- Изменить: `arch-docs/app/workflows/shared_assets/init_arch/references/checklist-architecture-artifact-updates.md:89-103`

**Интерфейсы:** нет (изменение только документации).

- [ ] **Шаг 1: Заменить секцию "Автоматические проверки"**

Заменить блок, который сейчас выглядит так:

```markdown
## Автоматические проверки

Перед закрытием пункта обязательно прогнать:

​```bash
python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py validate-contracts \
  --contracts-dir <arch-repo>/architecture/contracts
python .agents/skills/init-repo-arch-skill/scripts/analysis_guard.py validate-commits \
  --arch-repo-path <arch-repo>
​```

- `validate-contracts` проверяет, что файлы `*-sync.yml`/`*-async.yml` в `architecture/contracts/` — валидные OpenAPI/AsyncAPI.
- `validate-commits` проверяет, что `landscape.yaml: repository_state.head_commit` совпадает с `architecture/structure/<repo>.yml: analyzed_commit` для каждого сервиса — это два независимых места фиксации коммита анализа, и они не должны расходиться.

Если любая из команд вернула `ERROR`, пункт `architecture_artifact_updates` нельзя считать `completed` — сначала исправь расхождение в артефактах, затем повтори проверку.
```

на:

```markdown
## Автоматические проверки

Эти проверки не нужно запускать вручную — они выполняются автоматически сервисом на шаге `run_knowledge_lint` (см. `knowledge-workflow.md`) и блокируют переход к `validate_final`, если находят `ERROR`:

- обязательные секции для `hld.md`, `security.md`, `risks.md`, `tech-stack.md`, `roles-and-permissions.md`, `domain-entities.md`, `integrations-overview.md`, `constraints.md`, `requirements.md`, а также для каждого файла в `architecture/integrations/` и `features/`;
- `*-sync.yml` контракты в `architecture/contracts/` валидируются полноценно как OpenAPI через `openapi-spec-validator` (та же спецификация, что понимает Swagger) — документ, не прошедший эту проверку, не откроется в Swagger; `*-async.yml` валидируются полноценно как AsyncAPI 2.6.0 через `jsonschema` по официальной JSON Schema;
- файлы в `architecture/storage/` проверяются на наличие mapping `storage` с непустым `storage.type`;
- `landscape.yaml: entities.services[].repository_state.head_commit` сверяется с `architecture/structure/<id>.yml: repo_structure_map.analyzed_commit` для каждого сервиса — это два независимых места фиксации коммита анализа, и они не должны расходиться.

Если на шаге `run_knowledge_lint` появился `ERROR` по одной из этих проверок, пункт `architecture_artifact_updates` нельзя считать `completed` — сначала исправь расхождение в артефактах.
```

- [ ] **Шаг 2: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/shared_assets/init_arch/references/checklist-architecture-artifact-updates.md
git commit -m "docs(arch-docs): описать автоматические проверки architecture/* как service-side gate"
```

---

### Задача 11: Убрать ложные claims про progress-guard в `SKILL.md`

**Файлы:**
- Изменить: `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md`

**Интерфейсы:** нет (изменение только документации). Это текст, инжектируемый в промпт каждого worker'а через `prompts.py:139` (`_load_skill_md()`), и сейчас он противоречит собственному footer'у промпта (`prompts.py:206-207`: *"Сервис оркестрирует workflow и сам управляет progress state... не используй его как источник решений"*), настаивая, что агент обязан вызывать CLI-скрипт, которого в этом окружении не существует.

- [ ] **Шаг 1: Переписать claim про обязательный CLI в секции "Шаблоны и структура репозитория"**

Заменить строку (сейчас строка 36):

```markdown
Для обязательного пошагового исполнения workflow используй `scripts/analysis_guard.py`. Это не опциональная утилита, а основной механизм управления прогрессом анализа и защиты от пропуска этапов.
```

на:

```markdown
Прогресс workflow отслеживает сам сервис, а не агент: текущий шаг, завершённые шаги и зарегистрированные артефакты хранятся в состоянии сессии и обновляются автоматически по структурированному JSON-отчёту, который агент возвращает в конце каждого шага (`completed_actions`, `created_artifacts`, `open_questions_found`, `notes`). Агенту не нужно вызывать какой-либо CLI progress-guard самому — если промпт шага сообщает путь к progress-файлу, это только informational bridge, а не источник решений.
```

- [ ] **Шаг 2: Переписать финальное напоминание в "Правила работы"**

Заменить строку (сейчас строка 366):

```markdown
- **Не обходи `scripts/analysis_guard.py`, если задача реально идет по полному workflow этого skill. Для длинного анализа отсутствие progress-guard считается ошибкой исполнения skill.**
```

на:

```markdown
- **Не полагайся на память вместо фактического состояния артефактов.** Прогресс-guard в этом сервисе не CLI-утилита — это состояние сессии, которое сервис ведёт сам; агент должен строго следовать шагу и reference-чеклисту, которые получает в промпте, и не пропускать обязательные пункты checklist, даже если ничего не блокирует это технически на его стороне.
```

- [ ] **Шаг 3: Вручную убедиться, что других claims про обязательность `scripts/analysis_guard.py` не осталось**

Выполнить: `cd /Users/aanekraso2/github.com/znbiz/sdlc && grep -n "analysis_guard.py\|\.agents/skills" arch-docs/app/workflows/shared_assets/init_arch/SKILL.md`

Ожидается: останутся только блоки CLI-мнемоник `domain --...`/`repo --...`/`timeline --...` (вне скоупа плана, см. Глобальные ограничения).

- [ ] **Шаг 4: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/shared_assets/init_arch/SKILL.md
git commit -m "docs(arch-docs): убрать ложные инструкции про обязательный CLI analysis_guard.py для progress-guard"
```

---

### Задача 12: Полный регрессионный прогон

**Файлы:** нет (только проверка).

- [ ] **Шаг 1: Запустить полный test suite `arch-docs` с покрытием**

Выполнить: `cd arch-docs && .venv/bin/pytest --cov=app.workflows.init_arch.architecture_lint --cov-report=term-missing -v`
Ожидается: все тесты проходят; покрытие `architecture_lint.py` на уровне, близком к 100%.

- [ ] **Шаг 2: Запустить ruff по всему приложению `arch-docs`**

Выполнить: `cd arch-docs && .venv/bin/ruff check app tests`
Ожидается: код возврата 0.

- [ ] **Шаг 3: Убедиться, что правка текста SKILL.md корректно проходит через сборку промпта**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_prompts.py -v`
Ожидается: все проходят; если какой-то тест хардкодит удалённый текст как ожидаемую подстроку, обновить его под новую формулировку из задачи 11.

- [ ] **Шаг 4: Ещё раз перезапустить suite `init-repo-arch-skill`**

Выполнить: `cd init-repo-arch-skill && python3 -m pytest tests/ -v`
Ожидается: все проходят.
