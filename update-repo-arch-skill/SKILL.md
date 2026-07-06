---
name: update-repo-arch-skill
description: Обновление уже существующего архитектурного репозитория по дельте между предыдущим baseline-коммитом и текущим HEAD основной ветки. Use when an architecture repo already exists and the user wants to refresh it with changes from tracked repositories since the last analyzed commit — new commits, changed contracts, new integrations, updated storages, or newly discovered features. Scales to dozens of tracked repositories via triage-first, signal-routed delta analysis instead of full re-analysis. Do not use for first-time reconstruction of an existing system from scratch. Do not use for designing a new feature from scratch; use `new-feature-arch-skill`.
license: MIT
metadata:
  author: Nekrasov Aleksei
  version: "1.0"
---

# Навык обновления архитектурного репозитория

Используй этот навык, когда архитектурный репозиторий уже существует, и его нужно подтянуть к более свежему состоянию продукта без полного анализа с нуля.

Единица работы здесь — не репозиторий целиком, а дельта `<previous_baseline_commit>..HEAD`. При десятках отслеживаемых сервисов полный re-анализ каждого не масштабируется: вместо этого сначала классифицируется дельта во всех репозиториях (triage), затем точечно разбираются только те места, на которые указывает дельта (сигнальный роутинг), и в конце проверяются каскадные эффекты на другие репозитории.

## Граница применения

Используй этот skill, когда нужно обновить существующее `as-is` описание:

- появились новые коммиты в основных ветках отслеживаемых репозиториев
- изменились контракты, интеграции или хранилища
- появились новые или изменённые пользовательские сценарии
- предыдущий анализ устарел и нужно подтянуть только дельту

Не используй его:

- для первого наполнения архитектурного репозитория — это отдельный сценарий первичного анализа с нуля
- для проектирования нового поведения системы — используй `new-feature-arch-skill`
- если baseline-коммит ни для одного репозитория не найден (нет ни `architecture/landscape.yaml` с `repository_state.head_commit`, ни `architecture/structure/<repo>.yml` с `analyzed_commit`, ни `update-progress.json`, ни `repo-initialization-progress.yaml`) — это сценарий первичного наполнения архитектурного репозитория, не этого skill

## Стратегия

Сигнальный роутинг (изменившиеся файлы → категории артефактов) как основной механизм + семантика commit-сообщений как дополнительный сигнал приоритизации в triage, не как замена анализа файлов. Подробности — в [references/checklist-signal-routing.md](references/checklist-signal-routing.md).

## Артефакты для содержательной части анализа

Содержательные критерии анализа (что считать контрактом, что — интеграцией, как восстанавливать domain-entities и т.д.) применяются к ограниченной области, на которую указала дельта. Используй:

- [assets/architecture/](assets/architecture/) — шаблоны артефактов, если внутри дельты обнаружена новая структура, которой ещё нет в архитектурном репозитории
- [references/repository-layout.md](references/repository-layout.md) — структура архитектурного репозитория и соответствие артефактов шаблонам
- [references/checklist-repository-consistency-review.md](references/checklist-repository-consistency-review.md) — пары проверок для финальной согласованности
- содержательные чеклисты `references/checklist-*.md` — по категориям, см. таблицу в [references/checklist-targeted-deep-analysis.md](references/checklist-targeted-deep-analysis.md)
- [assets/release-note-template.md](assets/release-note-template.md) — шаблон release notes, заполняется на шаге `finalize_update`, см. [references/checklist-finalize-and-report.md](references/checklist-finalize-and-report.md)

Для временных клонов репозиториев используй локальный каталог `.temp/` в текущем workspace; если каталога нет, создай его и добавь в `.gitignore`.

Progress-файл (`update-progress.json` или другое имя из `--output`) — рабочий артефакт текущего прогона, а не источник истины (см. «Правила работы» и `checklist-baseline-and-triage.md`): он не должен попадать в коммит архитектурного репозитория. Если файл создаётся внутри архитектурного репозитория (а не вне его), перед `init` добавь его имя/паттерн (например, `update-progress*.json`) в `.gitignore` репозитория, если такой записи там ещё нет.

## Обязательный guard workflow

Этот skill исполняется в режиме `low freedom`: переход между этапами идёт через `scripts/update_guard.py`, а не только через текстовые инструкции в голове агента.

Минимальный цикл работы:

1. Если `<path>` для progress-файла лежит внутри архитектурного репозитория, перед первым запуском добавь его имя/паттерн в `.gitignore` репозитория (если такой записи там ещё нет). Затем создай progress-файл: `python .agents/skills/update-repo-arch-skill/scripts/update_guard.py init --output <path> --arch-repo-path <path-к-арх-репозиторию>`.
2. Перед началом каждого нового шага вызывай `... status` или `... validate` и сверяй текущий шаг.
3. Не переходи к следующему шагу, пока текущий не завершён.
4. После завершения шага переводи workflow дальше через `... advance`.
5. Если `validate`/`advance` показывает ошибку — сначала исправь progress-файл или артефакты, и только потом продолжай.

Если progress-файл уже существует (продолжение прерванного прогона), используй его фактический путь и имя. По умолчанию — `update-progress.json` в корне рабочей области.

## Границы сессий

Каждый шаг верхнего уровня (`load_baseline`/`refresh_repositories`, `triage_repositories`, `signal_mapping`, `targeted_deep_analysis`, `cascade_check`/`consistency_validation`, `finalize_update`) — это отдельная сессия работы агента. После `advance` в конец текущего шага агент **обязан остановиться** и явно попросить пользователя запустить продолжение в новой сессии — не продолжать работу в той же сессии дальше следующего шага.

- Перед остановкой убедись, что прогресс-файл сохранён через `advance` с содержательным `--note`, и что любой контекст, нужный для продолжения (что сделано, что осталось, какие репозитории/категории), зафиксирован в progress-файле, а не только в истории текущей сессии.
- В сообщении пользователю перед остановкой укажи: какой шаг завершён, путь к progress-файлу, какой шаг следующий, и что нужно открыть новую сессию и снова вызвать этот skill, чтобы продолжить — он сам найдёт текущий шаг через `status`.
- Исключение: `finalize_update` — терминальный шаг, после него весь прогон завершён, останавливаться и просить новую сессию не нужно. После него же удаляется сам progress-файл (см. `checklist-finalize-and-report.md`, шаг 5) — поэтому правило «зафиксировать контекст в progress-файле перед остановкой» к `finalize_update` не относится: весь нужный контекст к этому моменту уже должен быть перенесён в закоммиченные артефакты (`landscape.yaml`, `structure/<repo>.yml`, `release-notes/<YYYY-MM-DD>.md`).
- Внутри `targeted_deep_analysis` не делай дополнительных остановок между репозиториями — даже если значимых репозиториев много, шаг выполняется целиком в одной сессии, остановка только на его границе.

## Основные команды CLI

- `update_guard.py init --output <path> --arch-repo-path <path>`
- `update_guard.py status --progress <path>`
- `update_guard.py repo --progress <path> --name <repo> --register --repository-url <url> --main-branch <branch> --previous-baseline-commit <sha>`
- `update_guard.py repo --progress <path> --name <repo> --start` (только на шагах `triage_repositories` или `targeted_deep_analysis`)
- `update_guard.py repo --progress <path> --name <repo> --set-diff --classification <none|minor|significant> --new-baseline-commit <sha> --stat-summary "<...>"`
- `update_guard.py repo --progress <path> --name <repo> --complete --notes "<...>"`
- `update_guard.py signal --progress <path> --repo <repo> --add-category --category <id> --source-paths "<path1,path2>"`
- `update_guard.py signal --progress <path> --repo <repo> --category <id> --status completed --notes "<что обновлено>"`
- `update_guard.py cascade --progress <path> --register --source-repo <repo-A> --target <repo-B> --reason "<...>"`
- `update_guard.py cascade --progress <path> --complete --source-repo <repo-A> --target <repo-B> --notes "<...>"`
- `update_guard.py advance --progress <path> --step <step-id> --note "<что завершено>"`

Команда `validate` допустима для отладки, но не должна быть основным интерфейсом skill.

## Петля исполнения

Скилл работает в режиме **один шаг / один репозиторий / одна категория за раз**.

**Для шагов верхнего уровня:**
```
status → загрузить reference → выполнить один шаг → advance → СТОП: новая сессия
```
См. раздел «Границы сессий» выше — после `advance` агент не продолжает в той же сессии, кроме как для `finalize_update`.

**Для шага `triage_repositories`** — проходи **все** зарегистрированные репозитории за один проход, прежде чем переходить к глубокому разбору любого из них. Это и даёт масштабируемость на десятки сервисов: triage лёгкий (`git diff --stat`/`git log --oneline`), глубокий разбор — только там, где он оправдан.
```
status → загрузить checklist-baseline-and-triage.md
       → для каждого репозитория: git reset --hard origin/<main_branch> + git clean -fdx → refresh до HEAD → git diff --stat / git log --oneline
       → repo --set-diff --classification <none|minor|significant>
       → когда все репозитории классифицированы → advance → СТОП: новая сессия
```

**Для шага `signal_mapping`** — только для репозиториев с `diff_classification != none`:
```
status → загрузить checklist-signal-routing.md
       → для каждого такого репозитория: git diff --name-status → применить routing-таблицу
       → signal --add-category для каждой сработавшей категории
       → advance → СТОП: новая сессия
```

**Для шага `targeted_deep_analysis`** — вложенная петля по репозиториям, внутри неё — по категориям:
```
repo --start --name <repo>
  → для каждой зарегистрированной категории:
      загрузить reference из checklist-targeted-deep-analysis.md (таблица категория → чеклист)
      прочитать только изменившиеся файлы + их прямой контекст
      обновить существующий артефакт точечно (не пересоздавать)
      signal --category <id> --status completed --notes "<что обновлено>"
  → repo --complete --name <repo>
  → следующий репозиторий
→ когда все репозитории закрыты → advance → СТОП: новая сессия
```
Внутри этого шага не останавливайся между репозиториями — даже при большом числе `significant`-репозиториев шаг выполняется целиком в одной сессии.

**Для шага `cascade_check`**:
```
status → загрузить checklist-cascade-and-consistency.md
       → для каждой завершённой категории каждого репозитория: проверить, нужен ли cascade --register
       → для каждого зарегистрированного cascade_impact: проверить вторую сторону → cascade --complete
       → advance
```

**Для шага `consistency_validation`**: применить пары проверок из `checklist-cascade-and-consistency.md` / `checklist-repository-consistency-review.md`, но только к артефактам, тронутым в этом прогоне. После `advance` по `consistency_validation` — СТОП: новая сессия (шаги `cascade_check` и `consistency_validation` образуют одну сессию работы, см. «Границы сессий»).

**Для шага `finalize_update`**: см. [references/checklist-finalize-and-report.md](references/checklist-finalize-and-report.md). Это терминальный шаг — после него прогон завершён, останавливаться и просить новую сессию не нужно.

### Маппинг: шаг workflow → reference

| Шаг `workflow` | Reference-файл |
|---|---|
| `load_baseline`, `refresh_repositories`, `triage_repositories` | [references/checklist-baseline-and-triage.md](references/checklist-baseline-and-triage.md) |
| `signal_mapping` | [references/checklist-signal-routing.md](references/checklist-signal-routing.md) |
| `targeted_deep_analysis` | [references/checklist-targeted-deep-analysis.md](references/checklist-targeted-deep-analysis.md) |
| `cascade_check`, `consistency_validation` | [references/checklist-cascade-and-consistency.md](references/checklist-cascade-and-consistency.md) |
| `finalize_update` | [references/checklist-finalize-and-report.md](references/checklist-finalize-and-report.md) |

## Источники фактов

Те же категории и приоритеты, что при первичном анализе: **сильные** (API/gRPC routes, consumers/producers, integration/e2e тесты, миграции и схемы БД, OpenAPI/AsyncAPI/protobuf, Helm/Terraform/Compose/k8s, код оркестрации) доверяй без перепроверки; **средние** (README, `.env.example`, unit-тесты, диаграммы) перепроверяй по коду; **слабые** (названия папок, комментарии без подтверждения, wiki без привязки к коду) — только вспомогательный сигнал. Commit-сообщения для целей этого skill — отдельная, более слабая категория: используй их только для приоритизации в triage (см. «Семантика коммитов» в `checklist-signal-routing.md`), не как подтверждение факта.

## Правила работы

- Перед triage каждый репозиторий в `.temp/` обязательно приводится к состоянию GitLab: `git fetch origin` + `git reset --hard origin/<main_branch>` + `git clean -fdx`. Локальные изменения в `.temp/` всегда затираются без подтверждения — это временные клоны, а не рабочие копии.
- Сначала классифицируй дельту во **всех** репозиториях (triage), и только потом переходи к глубокому разбору. Не делай полный разбор первого репозитория, не дойдя до triage остальных.
- Не читай файлы, не попавшие в дельту, кроме случаев, когда нужен прямой контекст изменившегося кода (вызывающая или вызываемая сторона).
- Не переписывай артефакт с нуля, если изменилась только его часть: обновляй точечно, явно помечая, что устарело.
- Если дельта удаляет поведение (endpoint, поле, интеграция) — удаляй соответствующее описание из артефакта, не оставляй документацию мёртвого кода.
- Если `previous_baseline_commit` не найден в истории текущей ветки (force-push/rebase) — не пытайся вычислить дельту; зафиксируй `baseline_valid=false` и явно укажи, что репозиторию нужен полный пересмотр, а не точечное обновление.
- Если изменения тянут за собой новое поведение, которое является `to-be`, а не доработкой `as-is`, передавай эту часть в `new-feature-arch-skill`.
- Если изменившийся репозиторий не был включён в прошлый scope — явно зафиксируй расширение scope, не добавляй его в анализ молча.
- Не закрывай `cascade_check`, пока хотя бы один `cascade_impact` не в статусе `completed`.
- По умолчанию пиши обновления артефактов на русском языке. Английские термины оставляй только там, где это часть точного технического имени, протокола, библиотеки, endpoint, поля, enum, заголовка, env-переменной или другого кодового идентификатора.
- Если ссылаешься на кодовый файл, указывай путь вместе с репозиторием: `<repo-name>/src/...`, а не только внутренний путь.
- Не выдумывай поведение, не подтверждённое дельтой, кодом или конфигурацией.

## Чего не делать

- Не пересобирай весь архитектурный репозиторий, если изменился только локальный кусок системы.
- Не теряй baseline: каждый прогон должен заканчиваться зафиксированным `new_baseline_commit` по каждому обработанному репозиторию — обязательно в `architecture/landscape.yaml` и `architecture/structure/<repo>.yml`, а не только в `update-progress.json`, который может быть удалён или перезаписан до следующего прогона.
- Не путай дельту as-is с проектированием to-be — для последнего есть `new-feature-arch-skill`.
- Не считай прогон завершённым, если есть репозиторий с `diff_classification=significant` и незакрытыми категориями.
- Не подменяй пользовательский список отслеживаемых репозиториев автоматическим обнаружением соседних папок.

## Ожидаемые результаты

- обновлённый baseline по каждому репозиторию в `architecture/landscape.yaml` и `architecture/structure/<repo>.yml`; `update-progress.json` к концу прогона удалён (см. `checklist-finalize-and-report.md`, шаг 5) — это не итоговый артефакт, а рабочий файл на время прогона
- список изменившихся репозиториев и затронутых категорий артефактов
- обновлённые `architecture/` и `features/` только в затронутых местах
- закрытые или явно зафиксированные каскадные эффекты на другие репозитории
- обновлённый `open-questions.md`
- новый файл `release-notes/<YYYY-MM-DD>.md` ([assets/release-note-template.md](assets/release-note-template.md)) — единственный отчётный документ прогона: ссылки на обновлённые артефакты, дата, классификация по репозиториям, каскады, пробелы; без него прогон не считается завершённым (см. `checklist-finalize-and-report.md`)
