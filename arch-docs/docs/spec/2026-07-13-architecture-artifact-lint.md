# План внедрения: schema-driven валидация артефактов architecture/*

> **Для агентов-исполнителей:** ОБЯЗАТЕЛЬНЫЙ SUB-SKILL: используй superpowers:subagent-driven-development (рекомендуется) или superpowers:executing-plans для выполнения плана задача за задачей. Шаги отмечаются чекбоксами (`- [ ]`).

**Цель:** Заменить мёртвые инструкции `analysis_guard.py validate-contracts`/`validate-commits`, на которые сейчас ссылаются промпты worker'ов `init_arch` (но которых нет в сервисе `arch-docs`), на реальную, автоматическую, закодированную валидацию артефактов `architecture/*` — по тому же паттерну, который `knowledge_runtime.py` уже использует для слоя `wiki/`. Покрыть все 23 шаблона из `knowledge_base/` явным решением: либо новой проверкой, либо переиспользованием уже существующей, либо документированным обоснованным пропуском (см. таблицу покрытия ниже).

**Архитектура:** Добавить новый модуль `app/workflows/init_arch/architecture_lint.py`, который зеркалит существующий паттерн `run_knowledge_lint` из `knowledge_runtime.py`: чистые функции, читающие файлы внутри `arch_repo_dir` и возвращающие `list[str]` с issues в формате `ERROR:`. Подключить его к существующему вызову `run_knowledge_lint()`, чтобы он выполнялся автоматически на шаге workflow `run_knowledge_lint` (`StepId.RUN_KNOWLEDGE_LINT`) — том же quality gate, который уже блокирует переход к `validate_final` при наличии `ERROR:`.

**Дополнение (обновление плана после Задачи 3):** первоначальная версия плана оставляла 20 из 23 шаблонов вообще не подключёнными к коду сервиса — структура существовала только как текст, продублированный в чеклисты (см. «Предварительные правки» ниже), а сам worker писал `architecture/*.md` с нуля. Только 3 шаблона (`features-index-template.md`, `architecture/glossary-template.md`, `open-questions-template.md`) реально копируются кодом сервиса — `KnowledgeArtifactService._bootstrap_contents()` в `knowledge.py` пишет их **как есть**, включая литеральные плейсхолдеры вида `<термин>` и служебные HTML-комментарии вида `<!-- Не добавляй сюда... -->`, и только если целевой файл ещё не существует. Это уже сегодня скрытый баг: если worker не трогает `glossary.md` после bootstrap, финальный артефакт репозитория буквально содержит нерасшифрованные плейсхолдеры и комментарии для агента — и это никак не проверяется.

Чтобы закрыть оба пробела разом, план расширен двумя задачами:

- **Задача 3.1** — распространить уже существующий bootstrap-механизм (`_load_asset` + запись, только если файла ещё нет) на 9 markdown-артефактов из Задачи 2, используя их реальные шаблоны из `knowledge_base/architecture/*-template.md` как единственный источник содержимого (шаблоны не переписываются и не дублируются — читаются напрямую). Так сервис даёт worker'у готовый скелет с плейсхолдерами вместо чистого листа, вместо того чтобы worker писал структуру с нуля по инлайну в чеклисте.
- **Задача 7.1** — новая проверка в `architecture_lint.py`, которая детектирует **оставшиеся незаполненными** плейсхолдеры (`<...>`, извлечённые программно из тех же файлов шаблонов — единый источник, без ручного дублирования списка) и служебные HTML-комментарии (`<!--...-->`, универсальный маркер — комментарии никогда не должны попадать в synthesis-слой) в любом артефакте, который bootstrap мог создать из шаблона дословно: 9 markdown-артефактов Задачи 2, `glossary.md`, `open-questions.md`, `features-index.md`. Без этой проверки Задача 3.1 стала бы регрессией: `_lint_required_sections` видит заголовки секций в незаполненном шаблоне и репортует их как присутствующие, то есть сам факт существования секции перестаёт что-либо гарантировать по содержимому.

Обе задачи вместе отвечают на вопрос «шаблон подгружается или создаётся автоматически» — решение: **автоматически создаётся** (bootstrap из шаблона, как уже делается для 3 файлов), а не просто подгружается на лету для рендеринга воркеру, потому что у worker'а и так нет доступа к `shared_assets/`. Явное **не**-решение: сервис не делает автоматическую вырезку оставшихся плейсхолдеров/комментариев из финального артефакта — `architecture_lint.py` во всём плане является чистым валидатором (issue-list, никогда не мутирует файлы), и авто-вырезание рискует стереть частично отредактированный текст, который лишь похож на плейсхолдер. Вместо этого Задача 7.1 **блокирует** `validate_final`, пока worker сам не уберёт мусор — тот же паттерн quality gate, что и во всех остальных задачах плана.

## Таблица покрытия всех 23 шаблонов

| Шаблон в `knowledge_base/` | Целевой артефакт | Решение в этом плане |
| --- | --- | --- |
| `architecture/hld-template.md` | `architecture/hld.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/security-template.md` | `architecture/security.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/risks-template.md` | `architecture/risks.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/tech-stack-template.md` | `architecture/tech-stack.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/roles-and-permissions-template.md` | `architecture/roles-and-permissions.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/domain-entities-template.md` | `architecture/domain-entities.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/integrations-overview-template.md` | `architecture/integrations-overview.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/constraints-template.md` | `architecture/constraints.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/requirements-template.md` | `architecture/requirements.md` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка обязательных секций (Задача 2) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `AGENTS-template.md` | `AGENTS.md` | **Без bootstrap** — файл создаётся позже в workflow, чем `run_knowledge_lint` (см. Глобальные ограничения), поэтому шаблон сюда не копируется заранее. Проверка секций, только если файл уже существует (Задача 3) |
| `architecture/integration-template.md` | `architecture/integrations/<service>.md` (много файлов) | **Без bootstrap** — имя файла зависит от `<service>`, неизвестного заранее; worker создаёт с нуля по инлайну в чеклисте. Проверка секций по каждому файлу в каталоге (Задача 4) |
| `feature-template.md` | `features/<name>.md` (много файлов) | **Без bootstrap** — имя файла зависит от `<name>`, неизвестного заранее; worker создаёт с нуля по инлайну в чеклисте. Проверка секций по каждому файлу в каталоге (Задача 4) |
| `architecture/contract-template.yml` | `architecture/contracts/*-sync.yml` | Новая структурная OpenAPI-проверка (Задача 5) |
| `architecture/async-contract-template.yml` | `architecture/contracts/*-async.yml` | Новая полноценная валидация по вендоренной официальной JSON Schema AsyncAPI 2.6.0 через `jsonschema` (Задача 5) |
| `architecture/storage-template.yml` | `architecture/storage/*.yml` | Новая минимальная схема-проверка (Задача 6) |
| `architecture/landscape-template.yaml` | `architecture/landscape.yaml` | Bootstrap-скаффолдинг из шаблона (Задача 3.1) + проверка незаполненных плейсхолдеров/комментариев (Задача 7.1); уже используется и в проверке commit-консистентности (Задача 7) — отдельной проверки структуры не требуется, `entities.services` и так парсится и валидируется там |
| `architecture/repo-structure-map-template.yml` | `architecture/structure/<repo>.yml` | Уже используется в проверке commit-консистентности (Задача 7) |
| `architecture/glossary-template.md` | `glossary.md` | Структурной проверки не требуется — шаблон уже используется при bootstrap (`knowledge.py:209`), структуры сверх заголовка `# Глоссарий` шаблон не определяет. Но именно этот шаблон содержит служебный HTML-комментарий `<!-- Не добавляй сюда... -->` и плейсхолдер `<термин>` — теперь покрыт проверкой незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `architecture/support-repositories-template.md` | `architecture/support-repositories.md` | Шаблон **удалён** из `arch-docs` (нигде не читался кодом), структура инлайнена прямо в `checklist-repository-classification.md`. Артефакт `support-repositories.md` остаётся рабочей концепцией — фиксированных секций для отдельной lint-проверки нет (только повторяющиеся per-repo подзаголовки), см. Предварительные правки ниже |
| `features-index-template.md` | `features-index.md` | Уже используется при bootstrap и уже полноценно линтуется `_lint_feature_index` в `knowledge_runtime.py` — структурную проверку не дублируем, но добавляем проверку незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `open-questions-template.md` | `open-questions.md` | Уже используется при bootstrap и уже полноценно линтуется `_lint_open_questions_with_graph` — структурную проверку не дублируем, но добавляем проверку незаполненных плейсхолдеров/комментариев (Задача 7.1) |
| `index-template.md` | `wiki/index.md` (bootstrap-заглушка) | Шаблон **удалён** из `arch-docs` (нигде не читался кодом — `wiki/index.md` собирается независимым генератором `build_navigation_index()`, а сам шаблон успел разойтись с реальностью, до сих пор ссылаясь на мёртвую `analysis_guard compile`), см. Предварительные правки. Финальная версия артефакта проверяется `INDEX_REQUIRED_SECTIONS` в `knowledge_runtime.py` |
| `knowledge-log-template.md` | `wiki/log.md` | Шаблон **удалён** из `arch-docs` (нигде не читался кодом — `wiki/log.md` собирается независимым генератором `build_knowledge_log_stub()`), см. Предварительные правки. Артефакт полноценно линтуется `_lint_knowledge_log` в `knowledge_runtime.py` |
| `CLAUDE-template.md` | `CLAUDE.md` | Шаблон **удалён** из `arch-docs` (нигде не читался кодом, а содержимое тривиально — одна строка `@AGENTS.md`), см. Предварительные правки ниже |
| `repo-initialization-progress-template.yaml` | внешний progress-файл, не артефакт `arch_repo_dir` | Не применимо — этот файл не входит в архитектурный репозиторий и не проверяется knowledge lint'ом |

**Стек:** Python 3.14, pytest/pytest-asyncio, PyYAML и `openapi-spec-validator` (новые явные зависимости — PyYAML уже присутствует транзитивно через `langgraph`, план делает обе явными).

## Предварительные правки (уже выполнены до начала задач)

В ходе подготовки этого плана обнаружилось, что промпт worker'а (`prompts.py:139` инжектирует `SKILL.md` целиком + один reference-чеклист на шаг) и сами reference-чеклисты ссылались на файлы вида `assets/architecture/*-template.md` — путей, которых внутри контейнера worker'а физически нет (worker видит только `workspace_dir`/`arch_repo_dir`, каталог `shared_assets/` — часть файловой системы самого сервиса `arch-docs`, а не воркера). Это уже исправлено — правки не входят в задачи ниже, а являются их предпосылкой:

- В 10 файлах `arch-docs/app/workflows/shared_assets/init_arch/references/checklist-*.md` (`checklist-integrations-and-dependencies.md`, `checklist-roles-security-operability-risks.md`, `checklist-contracts-and-schemas.md`, `checklist-data-and-storage.md`, `checklist-domain-entities.md`, `checklist-repository-structure-mapping.md`, `checklist-repository-classification.md`, `checklist-features-and-index.md`, `checklist-tech-stack.md`) ссылки «по шаблону `assets/architecture/X-template.md`» заменены на инлайновую структуру артефакта прямо в тексте чеклиста — точный список обязательных секций/полей, совпадающий с тем, что валидирует `architecture_lint.py` из этого плана (единый источник структуры для промпта и для валидатора, пусть и продублированный текстуально).
- В `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md` убраны инструкции «используй шаблоны из `assets/`» и «используй `scripts/analysis_guard.py`» (оба пути недоступны воркеру) — заменены на описание того, что структура — в самих чеклистах, а прогресс workflow целиком отслеживает сервис через состояние сессии, не CLI.
- Удалены `arch-docs/app/workflows/shared_assets/knowledge_base/CLAUDE-template.md` и `arch-docs/app/workflows/shared_assets/knowledge_base/architecture/support-repositories-template.md` — ни один из них не читался кодом сервиса (`_load_asset` вызывается только для `features-index-template.md`, `architecture/glossary-template.md`, `open-questions-template.md`), а после инлайна структуры в чеклисты они стали полностью избыточны. Копии в `init-repo-arch-skill/assets/` и `update-repo-arch-skill/assets/` не тронуты — там у skill'а есть реальный доступ к файловой системе `assets/`.
- Удалены `arch-docs/app/workflows/shared_assets/knowledge_base/index-template.md` и `arch-docs/app/workflows/shared_assets/knowledge_base/knowledge-log-template.md` — ни один из них не читался кодом сервиса (проверено `grep` по `app/` и `tests/`: ни один код-путь не открывает эти файлы), а их целевые артефакты (`wiki/index.md`, `wiki/log.md`) генерируются полностью независимым Python-кодом — `build_navigation_index()` и `build_knowledge_log_stub()` в `knowledge_runtime.py` — с собственным захардкоженным содержимым, а не чтением этих шаблонов. Хуже того, `index-template.md` уже успел разойтись с реальностью: в разделе «Compile Rules» он всё ещё ссылался на `analysis_guard compile` — ту самую мёртвую CLI-команду, ради устранения которой существует этот план. Оставлять такой файл лежать рядом с генератором, который его игнорирует, — источник будущей путаницы для человека, который решит, что это актуальный источник структуры.

## Глобальные ограничения

- Код и идентификаторы на английском; русский — только для комментариев/документации там, где это действительно нужно (по гайдлайнам pylines этого репозитория).
- Новая/изменённая логика должна поставляться с тестами, покрывающими дельту на уровне, близком к 100%, для нового модуля.
- Не изменять собственные `scripts/analysis_guard/*.py` в `init-repo-arch-skill` — это отдельный, независимо протестированный standalone skill; план переносит в `arch-docs` только *логику* валидации, не импортирует её (общего пакета между двумя репозиториями нет).
- Не изменять `init-repo-arch-skill/assets/`, `init-repo-arch-skill/references/`, `update-repo-arch-skill/assets/`, `update-repo-arch-skill/references/` — правки в «Предварительных правках» выше касаются только копий внутри `arch-docs`, у которых нет доступа к файловой системе `assets/` в контейнере worker'а. У отдельно устанавливаемых skill'ов эта проблема не воспроизводится.
- Вне скоупа (явно, не браться): переписывание CLI-мнемоник `domain --...`/`repo --...`/`timeline --...` по всему `SKILL.md` и checklist-референсам — они описывают операции, которые сервис уже выполняет иначе через `InitArchState`/`domain/operations.py`, и распутывание всех их — отдельная, более крупная задача на будущее.
- Каждая новая проверка обязательных секций требует существования файла (`ERROR: отсутствует ...`), кроме `AGENTS.md` — он по договорённости репозитория (`repository-layout.md`) создаётся позже в workflow, чем `run_knowledge_lint`, поэтому для него проверяются только секции, если файл уже есть.
- Bootstrap-скаффолдинг (Задача 3.1) и проверка плейсхолдеров/комментариев (Задача 7.1) — только для артефактов с предсказуемым, известным заранее именем файла (9 markdown из Задачи 2 + `glossary.md`/`open-questions.md`/`features-index.md`). Артефакты с именем, зависящим от `<service>`/`<name>` (`architecture/integrations/*.md`, `features/*.md`, `architecture/contracts/*.yml`, `architecture/storage/*.yml`, `architecture/structure/*.yml`) не скаффолдятся — их по-прежнему пишет worker с нуля по инлайну в чеклисте; расширение этого списка — отдельная будущая задача, не входит в скоуп.
- `architecture_lint.py` во всём плане — чистый валидатор: возвращает `list[str]` issues и никогда не пишет и не мутирует файлы. Задача 7.1 не удаляет и не «чистит» плейсхолдеры/комментарии автоматически — она только детектирует их и блокирует `validate_final`, пока worker не уберёт их сам. Автоматическая вырезка контента намеренно не реализуется: эвристика «похоже на плейсхолдер» недостаточно надёжна, чтобы гарантированно не стереть частично отредактированный текст.

---

## Структура файлов

- **Создать:** `arch-docs/app/workflows/init_arch/architecture_lint.py` — новый модуль со всеми проверками.
- **Создать:** `arch-docs/app/workflows/init_arch/schemas/asyncapi-2.6.0.json` — вендоренная официальная JSON Schema AsyncAPI 2.6.0.
- **Создать:** `arch-docs/tests/workflows/init_arch/test_architecture_lint.py` — юнит-тесты для нового модуля.
- **Изменить:** `arch-docs/app/workflows/init_arch/knowledge_runtime.py` — подключить `lint_architecture_artifacts` внутри `run_knowledge_lint()`.
- **Изменить:** `arch-docs/app/workflows/init_arch/knowledge.py` — расширить `_bootstrap_contents()` bootstrap-скаффолдингом 9 markdown-артефактов из шаблонов (Задача 3.1).
- **Изменить:** `arch-docs/tests/workflows/init_arch/test_knowledge.py` — тесты на новый bootstrap-скаффолдинг (Задача 3.1).
- **Изменить:** `arch-docs/pyproject.toml` — добавить явные зависимости `pyyaml`, `openapi-spec-validator`, `jsonschema`.
- **Изменить:** `arch-docs/app/workflows/shared_assets/init_arch/references/checklist-architecture-artifact-updates.md` — заменить мёртвый bash-блок `analysis_guard.py validate-contracts`/`validate-commits` описанием нового автоматического gate.
- **Изменить:** `arch-docs/app/workflows/shared_assets/init_arch/SKILL.md` — убрать два ложных утверждения о том, что `scripts/analysis_guard.py` — обязательный механизм progress-guard.

**Вне скоупа:** этот план не трогает файлы в `init-repo-arch-skill` — ни `assets/`, ни `references/`, ни `tests/fixtures/`. `arch-docs/tests/workflows/init_arch/test_knowledge.py` читает общую фикстуру `init-repo-arch-skill/tests/fixtures/valid_arch_repo` по абсолютному пути; после Задачи 8 один тест на этой фикстуре (`test_valid_arch_repo_smoke_bootstrap_compile_and_lint`) закономерно станет падать и помечается `xfail` — приведение самой фикстуры в соответствие новым проверкам осталось за пределами этого плана и должно решаться отдельной задачей в репозитории `init-repo-arch-skill`.

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

- [x] **Шаг 1: Написать падающие тесты**

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

- [x] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: `ModuleNotFoundError: No module named 'app.workflows.init_arch.architecture_lint'`.

- [x] **Шаг 3: Написать минимальную реализацию**

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

- [x] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: `4 passed`

- [x] **Шаг 5: Коммит**

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

- [x] **Шаг 1: Написать падающие тесты**

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

- [x] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_agents_md`
Ожидается: падение с `AttributeError`.

- [x] **Шаг 3: Написать минимальную реализацию**

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

- [x] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: все тесты проходят.

- [x] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): добавить опциональную проверку секций AGENTS.md"
```

---

### Задача 3.1 (НОВАЯ): Bootstrap-скаффолдинг 9 markdown-артефактов и `landscape.yaml` из шаблонов `knowledge_base/`

**Контекст:** сейчас `KnowledgeArtifactService._bootstrap_contents()` копирует из `knowledge_base/` только 3 шаблона (`features-index-template.md`, `architecture/glossary-template.md`, `open-questions-template.md`) — остальные 9 markdown-артефактов из Задачи 2 worker обязан писать с нуля, ориентируясь только на инлайн-структуру в чеклистах, хотя их реальные шаблоны (`architecture/hld-template.md` и т.д.) уже лежат в `knowledge_base/architecture/` и нигде не используются. Эта задача распространяет уже существующий bootstrap-паттерн (пишем, только если файла ещё нет) на эти 9 файлов — так worker получает готовый скелет с плейсхолдерами вместо чистого листа. `AGENTS.md` намеренно не входит — он создаётся позже в workflow (см. Глобальные ограничения).

**Ради максимального покрытия** та же логика распространяется на `architecture/landscape.yaml` из `architecture/landscape-template.yaml`. В отличие от per-service артефактов (`integrations/<service>.md`, `contracts/<service>-*.yml`, `storage/<service>.yml`, `structure/<repo>.yml`), у `landscape.yaml` **предсказуемое, единственное имя файла**, известное заранее — точно как у 9 markdown-артефактов, поэтому нет структурной причины оставлять его без bootstrap, в отличие от per-service файлов, у которых имя зависит от ещё не проанализированных сервисов.

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/knowledge.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_knowledge.py`

**Интерфейсы:**
- Производит: `_ARCHITECTURE_TEMPLATE_ASSETS: Final[dict[str, str]]` (целевой relative_path -> relative_path шаблона внутри `knowledge_base/`), включённый в `_bootstrap_contents()`.
- Потребляет: `ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS` из `architecture_lint.py` только как справочный список ключей (не импортируется — `knowledge.py` не должен знать о `architecture_lint.py`, зависимость идёт в обратную сторону: `knowledge_runtime.py` вызывает `architecture_lint.py`, а `knowledge.py` — соседний независимый модуль).

- [x] **Шаг 1: Написать падающий тест**

Добавить в `arch-docs/tests/workflows/init_arch/test_knowledge.py`:

```python
@pytest.mark.asyncio
async def test_bootstrap_arch_repo_scaffolds_architecture_markdown_from_templates(tmp_path: Path) -> None:
    asset_loader = WorkflowAssetLoader(
        Path("/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/app/workflows/shared_assets")
    )
    service = KnowledgeArtifactService(asset_loader=asset_loader)

    result = await service.bootstrap_arch_repo(_make_session(), arch_repo_dir=str(tmp_path / "arch-repo"))

    hld_path = tmp_path / "arch-repo" / "architecture" / "hld.md"
    assert hld_path.exists()
    assert "## Контекстная диаграмма" in hld_path.read_text(encoding="utf-8")
    assert any(artifact.artifact_path == "architecture/hld.md" for artifact in result.session.artifacts)


@pytest.mark.asyncio
async def test_bootstrap_arch_repo_scaffolds_landscape_yaml_from_template(tmp_path: Path) -> None:
    asset_loader = WorkflowAssetLoader(
        Path("/Users/aanekraso2/github.com/znbiz/sdlc/arch-docs/app/workflows/shared_assets")
    )
    service = KnowledgeArtifactService(asset_loader=asset_loader)

    result = await service.bootstrap_arch_repo(_make_session(), arch_repo_dir=str(tmp_path / "arch-repo"))

    landscape_path = tmp_path / "arch-repo" / "architecture" / "landscape.yaml"
    assert landscape_path.exists()
    assert "entities:" in landscape_path.read_text(encoding="utf-8")
    assert any(artifact.artifact_path == "architecture/landscape.yaml" for artifact in result.session.artifacts)


@pytest.mark.asyncio
async def test_bootstrap_arch_repo_does_not_overwrite_existing_architecture_markdown(tmp_path: Path) -> None:
    arch_repo_dir = tmp_path / "arch-repo"
    (arch_repo_dir / "architecture").mkdir(parents=True)
    (arch_repo_dir / "architecture" / "hld.md").write_text("# уже написано worker'ом\n", encoding="utf-8")
    service = KnowledgeArtifactService()

    await service.bootstrap_arch_repo(_make_session(), arch_repo_dir=str(arch_repo_dir))

    assert (arch_repo_dir / "architecture" / "hld.md").read_text(encoding="utf-8") == "# уже написано worker'ом\n"
```

- [x] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_knowledge.py -v -k "architecture_markdown or landscape_yaml"`
Ожидается: первые два теста падают (`hld.md`/`landscape.yaml` не создаются), третий (overwrite-guard) проходит уже сейчас.

- [x] **Шаг 3: Написать минимальную реализацию**

В `arch-docs/app/workflows/init_arch/knowledge.py` добавить рядом с `_ARTIFACT_KINDS`:

```python
_ARCHITECTURE_TEMPLATE_ASSETS: Final[dict[str, str]] = {
    "architecture/hld.md": "architecture/hld-template.md",
    "architecture/security.md": "architecture/security-template.md",
    "architecture/risks.md": "architecture/risks-template.md",
    "architecture/tech-stack.md": "architecture/tech-stack-template.md",
    "architecture/roles-and-permissions.md": "architecture/roles-and-permissions-template.md",
    "architecture/domain-entities.md": "architecture/domain-entities-template.md",
    "architecture/integrations-overview.md": "architecture/integrations-overview-template.md",
    "architecture/constraints.md": "architecture/constraints-template.md",
    "architecture/requirements.md": "architecture/requirements-template.md",
    "architecture/landscape.yaml": "architecture/landscape-template.yaml",
}
```

Обновить `_bootstrap_contents`, добавив эти 10 ключей через тот же `_load_asset`:

```python
def _bootstrap_contents(self, session: WorkflowSessionRecord) -> dict[str, str]:
    repositories = [
        {"name": repository.repository_name, "analysis_status": repository.analysis_status}
        for repository in session.repositories
    ]
    contents = {
        "features-index.md": self._load_asset("features-index-template.md"),
        "glossary.md": self._load_asset("architecture/glossary-template.md"),
        "open-questions.md": self._load_asset("open-questions-template.md"),
        "wiki/index.md": build_navigation_index(
            pathlib.Path(),
            session.product_name,
            repositories,
        ).replace("](./", "](../"),
        "wiki/log.md": build_knowledge_log_stub(),
        "wiki/maps/compile-report.md": build_compile_report_stub(),
    }
    for target_path, template_path in _ARCHITECTURE_TEMPLATE_ASSETS.items():
        contents[target_path] = self._load_asset(template_path)
    return contents
```

Логика "пишем, только если файла ещё нет" в `bootstrap_arch_repo` (строки 84-88) уже не требует изменений — она уже безусловно применяется ко всем ключам `_bootstrap_contents()`.

- [x] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_knowledge.py -v`
Ожидается: все тесты проходят, включая уже существующий `test_valid_arch_repo_smoke_bootstrap_compile_and_lint` (фикстура уже содержит реальный, заполненный `architecture/hld.md`/`architecture/landscape.yaml` — bootstrap их не тронет, сработает ветка "файл уже существует").

- [x] **Шаг 5: Полный регрессионный прогон и ruff**

Выполнить: `cd arch-docs && .venv/bin/pytest -q && .venv/bin/ruff check app/workflows/init_arch/knowledge.py tests/workflows/init_arch/test_knowledge.py`
Ожидается: все тесты проходят, `ruff` чист.

- [ ] **Шаг 6: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/knowledge.py arch-docs/tests/workflows/init_arch/test_knowledge.py
git commit -m "feat(arch-docs): bootstrap-скаффолдинг 9 architecture/*.md артефактов и landscape.yaml из реальных шаблонов knowledge_base/"
```

**Мини-отчёт (2026-07-13):**

- Добавлены regression-тесты на bootstrap `architecture/hld.md`, `architecture/landscape.yaml` и на запрет перезаписи уже существующего `architecture/hld.md`.
- Red подтверждён командой `./.venv/bin/pytest tests/workflows/init_arch/test_knowledge.py -v -k "architecture_markdown or landscape_yaml"`: два новых теста падали из-за отсутствующих `hld.md` и `landscape.yaml`, overwrite-guard уже проходил.
- В `knowledge.py` добавлен `_ARCHITECTURE_TEMPLATE_ASSETS` и подключён в `_bootstrap_contents()`; bootstrap теперь копирует 9 markdown-шаблонов `architecture/*-template.md` и `architecture/landscape-template.yaml`, сохраняя существующее правило "не перезаписывать готовый файл".
- Green подтверждён `./.venv/bin/pytest tests/workflows/init_arch/test_knowledge.py -v`: `12 passed`.
- Регрессия подтверждена `./.venv/bin/pytest -q`: `372 passed, 3 warnings`. Линт подтверждён `./.venv/bin/ruff check app/workflows/init_arch/knowledge.py tests/workflows/init_arch/test_knowledge.py`: `All checks passed!`.

---

### Задача 4: `architecture_lint.py` — обязательные секции для файлов в `integrations/` и `features/`

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/architecture_lint.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`

**Интерфейсы:**
- Производит: `INTEGRATION_REQUIRED_SECTIONS`, `FEATURE_REQUIRED_SECTIONS`, `_lint_directory_documents(arch_repo_path: Path, relative_dir: str, required_sections: tuple[str, ...]) -> list[str]`, включённую в `lint_architecture_artifacts` дважды.

- [x] **Шаг 1: Написать падающие тесты**

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

- [x] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_directory_documents`
Ожидается: падение с `AttributeError`.

- [x] **Шаг 3: Написать минимальную реализацию**

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

- [x] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: все тесты проходят.

- [x] **Шаг 5: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): добавить проверку обязательных секций для integrations/ и features/"
```

**Мини-отчёт по задаче 4 (2026-07-13):**

- Добавлены `INTEGRATION_REQUIRED_SECTIONS` и `FEATURE_REQUIRED_SECTIONS` в `architecture_lint.py`.
- Добавлен `_lint_directory_documents(...)`, который обходит `architecture/integrations/*.md` и `features/*.md`, не падает при отсутствии каталога и репортит пропущенные секции по каждому файлу отдельно.
- `lint_architecture_artifacts(...)` расширен двумя новыми вызовами directory-lint, поэтому покрытие Task 4 теперь входит в общий architecture artifact lint module.
- TDD зафиксирован свежим red-green циклом:
  - `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_directory_documents` → `3 failed` с `AttributeError` до реализации.
  - `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v` → `10 passed` после реализации.

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

### Задача 7.1 (НОВАЯ): `architecture_lint.py` — детектировать незаполненные плейсхолдеры и служебные комментарии шаблонов

**Контекст:** Задача 3.1 сделала bootstrap 9 markdown-артефактов из реальных шаблонов дословно, включая плейсхолдеры вида `<риск или пробел в документации>` и служебные HTML-комментарии вида `<!-- Не добавляй сюда... -->` (пример уже существует сегодня в `architecture/glossary-template.md`, который bootstrap копирует с самого начала плана, до этой задачи). Без отдельной проверки такой незаполненный скелет проходит `_lint_required_sections` (заголовки секций физически присутствуют) и попадает в финальный knowledge-репозиторий как есть — то есть worker может забыть заполнить файл, а lint этого не заметит. Эта задача закрывает разрыв: находит плейсхолдеры и комментарии, оставшиеся в финальном содержимом, и блокирует ими `validate_final` (тот же механизм `ERROR:`, что и во всех остальных проверках).

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/architecture_lint.py`
- Тест: `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`

**Интерфейсы:**
- Производит: `_lint_template_residue(arch_repo_path: Path) -> list[str]`, включённую в `lint_architecture_artifacts`. Известные плейсхолдеры извлекаются программно из тех же файлов шаблонов в `knowledge_base/` (единый источник — список не дублируется руками), известные комментарии детектируются универсальным regex `<!--.*?-->` (в synthesis-слое HTML-комментариев не должно быть в принципе, вне зависимости от шаблона-источника).
- Область действия: 9 markdown-артефактов из `ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS` (ключи переиспользуются напрямую, отдельный список не заводим) + `glossary.md`, `features-index.md`, `open-questions.md` + `architecture/landscape.yaml` — все артефакты, которые могут быть bootstrap-скопированы из шаблона дословно (Задача 3.1). `AGENTS.md`, `architecture/integrations/*.md`, `features/*.md`, контракты, storage и `architecture/structure/*.yml` — вне области действия (не bootstrap-ятся, см. Задачу 3.1 и Глобальные ограничения).

- [ ] **Шаг 1: Написать падающие тесты**

Добавить в конец `arch-docs/tests/workflows/init_arch/test_architecture_lint.py`:

```python
def test_lint_template_residue_skips_missing_files(tmp_path: Path) -> None:
    issues = architecture_lint._lint_template_residue(tmp_path)

    assert issues == []


def test_lint_template_residue_flags_unfilled_placeholder(tmp_path: Path) -> None:
    _write(tmp_path, "architecture/risks.md", "# Риски\n\n## Категории\n\n1. <риск или пробел в документации>\n")

    issues = architecture_lint._lint_template_residue(tmp_path)

    assert any(
        "незаполненный плейсхолдер" in issue and "architecture/risks.md" in issue for issue in issues
    )


def test_lint_template_residue_flags_unfilled_comment(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "glossary.md",
        "# Глоссарий\n\n"
        '<!-- Не добавляй сюда служебный вводный абзац про "этот файл фиксирует..." или список уже '
        'проанализированных репозиториев. В итоговом glossary.md после заголовка файла должен сразу идти '
        'таблица терминов, без промежуточного заголовка "Термины". -->\n\n'
        "| Термин | Определение | Источник |\n| --- | --- | --- |\n"
        "| API | Программный интерфейс | gateway-service/README.md |\n",
    )

    issues = architecture_lint._lint_template_residue(tmp_path)

    assert any("незаполненный служебный комментарий" in issue and "glossary.md" in issue for issue in issues)


def test_lint_template_residue_passes_when_content_is_filled_in(tmp_path: Path) -> None:
    _write(tmp_path, "architecture/risks.md", "# Риски\n\n## Категории\n\n1. Нет автоматических бэкапов БД\n")
    _write(
        tmp_path,
        "glossary.md",
        "# Глоссарий\n\n| Термин | Определение | Источник |\n| --- | --- | --- |\n"
        "| CLI-токен | Токен обмена для CLI-логина | gateway-service/src/api/auth.py |\n",
    )

    issues = architecture_lint._lint_template_residue(tmp_path)

    assert issues == []


def test_lint_template_residue_flags_unfilled_landscape_placeholder(tmp_path: Path) -> None:
    _write(tmp_path, "architecture/landscape.yaml", "system:\n  name: <название-системы>\n")

    issues = architecture_lint._lint_template_residue(tmp_path)

    assert any(
        "незаполненный плейсхолдер" in issue and "architecture/landscape.yaml" in issue for issue in issues
    )
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v -k lint_template_residue`
Ожидается: падение с `AttributeError`.

- [ ] **Шаг 3: Написать минимальную реализацию**

В `arch-docs/app/workflows/init_arch/architecture_lint.py` добавить импорт `re` рядом с остальными импортами (после `import json`):

```python
import re
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
    issues.extend(_lint_storage(arch_repo_path))
    issues.extend(_lint_commit_consistency(arch_repo_path))
    issues.extend(_lint_template_residue(arch_repo_path))
    return issues
```

Добавить в конец файла:

```python
_RESIDUE_SOURCE_TEMPLATES: Final[tuple[str, ...]] = (
    "architecture/hld-template.md",
    "architecture/security-template.md",
    "architecture/risks-template.md",
    "architecture/tech-stack-template.md",
    "architecture/roles-and-permissions-template.md",
    "architecture/domain-entities-template.md",
    "architecture/integrations-overview-template.md",
    "architecture/constraints-template.md",
    "architecture/requirements-template.md",
    "architecture/glossary-template.md",
    "features-index-template.md",
    "open-questions-template.md",
    "architecture/landscape-template.yaml",
)
_RESIDUE_TARGET_PATHS: Final[tuple[str, ...]] = (
    *ARCHITECTURE_MARKDOWN_REQUIRED_SECTIONS,
    "glossary.md",
    "features-index.md",
    "open-questions.md",
    "architecture/landscape.yaml",
)
_PLACEHOLDER_PATTERN: Final[re.Pattern[str]] = re.compile(r"<[^<>\n]{1,120}>")
_COMMENT_PATTERN: Final[re.Pattern[str]] = re.compile(r"<!--.*?-->", re.DOTALL)
_KNOWLEDGE_BASE_DIR: Final[Path] = Path(__file__).resolve().parent.parent / "shared_assets" / "knowledge_base"

_known_template_placeholders_cache: frozenset[str] | None = None


def _known_template_placeholders() -> frozenset[str]:
    global _known_template_placeholders_cache  # noqa: PLW0603
    if _known_template_placeholders_cache is None:
        tokens: set[str] = set()
        for relative_path in _RESIDUE_SOURCE_TEMPLATES:
            template_text = (_KNOWLEDGE_BASE_DIR / relative_path).read_text(encoding="utf-8")
            tokens.update(_PLACEHOLDER_PATTERN.findall(template_text))
        _known_template_placeholders_cache = frozenset(tokens)
    return _known_template_placeholders_cache


def _lint_template_residue(arch_repo_path: Path) -> list[str]:
    known_placeholders = _known_template_placeholders()
    issues: list[str] = []
    for relative_path in _RESIDUE_TARGET_PATHS:
        artifact_path = arch_repo_path / relative_path
        if not artifact_path.exists():
            continue

        content = artifact_path.read_text(encoding="utf-8")
        for comment in _COMMENT_PATTERN.findall(content):
            issues.append(
                f"ERROR: {relative_path} содержит незаполненный служебный комментарий шаблона: `{comment.strip()}`"
            )
        for placeholder in sorted(known_placeholders):
            if placeholder in content:
                issues.append(f"ERROR: {relative_path} содержит незаполненный плейсхолдер шаблона: `{placeholder}`")
    return issues
```

`Path(__file__).resolve().parent.parent` — `architecture_lint.py` лежит в `app/workflows/init_arch/`, а `knowledge_base/` — в `app/workflows/shared_assets/`, то есть на уровень выше и в соседний каталог; тот же уровень вложенности, который уже использует `WorkflowAssetLoader` (`app/workflows/shared_assets/loader.py:7`), но без зависимости от него — модуль остаётся самодостаточным.

- [ ] **Шаг 4: Запустить тесты и убедиться, что они проходят**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_architecture_lint.py -v`
Ожидается: все тесты проходят.

- [ ] **Шаг 5: Запустить ruff и исправить**

Выполнить: `cd arch-docs && .venv/bin/ruff check app/workflows/init_arch/architecture_lint.py tests/workflows/init_arch/test_architecture_lint.py --fix`
Ожидается: код возврата 0.

- [ ] **Шаг 6: Полный регрессионный прогон**

Выполнить: `cd arch-docs && .venv/bin/pytest -q`
Ожидается: все тесты проходят, включая `test_valid_arch_repo_smoke_bootstrap_compile_and_lint` — фикстура из Задачи 9 содержит только заполненный реальный контент, без плейсхолдеров и комментариев, поэтому `_lint_template_residue` не должна на ней ничего репортить.

- [ ] **Шаг 7: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/architecture_lint.py arch-docs/tests/workflows/init_arch/test_architecture_lint.py
git commit -m "feat(arch-docs): детектировать незаполненные плейсхолдеры и служебные комментарии шаблонов в architecture-артефактах"
```

---

### Задача 8: Подключить `lint_architecture_artifacts` к `run_knowledge_lint`

**Файлы:**
- Изменить: `arch-docs/app/workflows/init_arch/knowledge_runtime.py:393-451` (функция `run_knowledge_lint`)
- Тест: `arch-docs/tests/workflows/init_arch/test_knowledge_runtime.py`

**Интерфейсы:**
- Потребляет: `lint_architecture_artifacts(arch_repo_path: Path) -> list[str]` из `architecture_lint.py` (задачи 2-7 и 7.1 — residue-проверка уже включена внутри той же функции, здесь ничего дополнительно вызывать не нужно).
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

- [ ] **Шаг 5: Запустить полный knowledge test suite и разобраться с тестом на внешней фикстуре**

Выполнить: `cd arch-docs && .venv/bin/pytest tests/workflows/init_arch/test_knowledge_runtime.py tests/workflows/init_arch/test_knowledge.py -v`

Ожидается: `test_valid_arch_repo_smoke_bootstrap_compile_and_lint` теперь FAIL — он копирует `init-repo-arch-skill/tests/fixtures/valid_arch_repo` (репозиторий **вне** скоупа этого плана, см. Глобальные ограничения) и ассертит `not any(issue.startswith("ERROR:") ...)`, а эта фикстура никогда не была валидной относительно проверок из задач 2-7.1 — с этого шага и до тех пор, пока кто-то отдельно не приведёт фикстуру в `init-repo-arch-skill` в соответствие (вне этого плана, отдельная задача в *том* репозитории), тест будет падать по объективной причине, а не из-за бага в `arch-docs`.

Не чинить фикстуру в рамках этого плана. Вместо этого пометить тест как заведомо падающий по внешней причине — в `arch-docs/tests/workflows/init_arch/test_knowledge.py` добавить маркер прямо над определением теста:

```python
@pytest.mark.xfail(
    reason=(
        "init-repo-arch-skill/tests/fixtures/valid_arch_repo ещё не приведена в соответствие с "
        "architecture_lint.py (задачи 2-7.1) — фикстура лежит в отдельном репозитории, вне скоупа "
        "этого плана; обновление фикстуры нужно делать отдельной задачей в init-repo-arch-skill"
    ),
    strict=False,
)
async def test_valid_arch_repo_smoke_bootstrap_compile_and_lint(tmp_path: Path) -> None:
```

`strict=False` — потому что тест должен оставаться "не красным" в CI `arch-docs` уже сейчас, но не должен молча начать проходить незамеченным: если кто-то обновит фикстуру в `init-repo-arch-skill` независимо и тест внезапно начнёт проходить, `pytest` сообщит об этом отдельно (`XPASS`), а не тихо смолчит.

- [ ] **Шаг 6: Коммит**

```bash
cd /Users/aanekraso2/github.com/znbiz/sdlc
git add arch-docs/app/workflows/init_arch/knowledge_runtime.py arch-docs/tests/workflows/init_arch/test_knowledge_runtime.py arch-docs/tests/workflows/init_arch/test_knowledge.py
git commit -m "feat(arch-docs): подключить lint_architecture_artifacts к run_knowledge_lint"
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
