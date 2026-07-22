# E2E-проверка progress-снепшота через фронт (без живых LLM) — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Цель:** Собрать e2e-проверку фичи progress-снепшота (`arch-docs/docs/superpowers/plans/2026-07-18-workflow-progress-snapshot.md`, уже реализована и смержена) на реальном docker-compose стеке (`nginx` + `arch-docs` backend + `arch-docs-front` + Postgres): три синтетических git-репозитория с историей за год реально анализируются через детерминированные шаги `init_arch`, запущенного через UI, и на каждом шаге проверяется, что `repo-initialization-progress.yaml` на диске контейнера соответствует реальному состоянию `WorkflowSessionRecord`.

**Скоуп (согласовано с пользователем):** без живых вызовов `claude`/`codex` CLI — в `.env.docker` нет `ANTHROPIC_API_KEY`, volume'ы `codex-auth`/`claude-auth` не сконфигурированы для неинтерактивного запуска. Прогон идёт через фронт до первого LLM-шага (`clone_repositories`), который **ожидаемо** падает с auth-ошибкой (`task_runner.py`'s `FAILURE_REASON_AUTH_EXPIRED`, см. `_CLAUDE_AUTH_ERROR_SUBSTRINGS`/`_CODEX_AUTH_ERROR_EXIT_CODES`) — это происходит быстро (ошибка на старте CLI-процесса, не таймаут долгого анализа), 3 раза ретраится, затем уходит в `handle_error`/interrupt. Именно на этом пути проверяется, что снепшот пишется и на успешных детерминированных шагах, и на interrupt после исчерпания ретраев. Восстановление (`resume_init_arch_from_snapshot`) в этом плане НЕ проверяется через браузер — оно доступно только через MCP-инструмент (см. предыдущий план, раздел "Out of scope"); отдельная проверка запланирована как backend-level тест, не через Playwright.

**Архитектура:** Три вспомогательных Python-скрипта (не пакет, локальные утилиты для e2e) генерируют синтетические git-репозитории с закоммиченной историей за ~12 месяцев (1-2 коммита/месяц, `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` для контроля `created_at`). Эти репозитории копируются в docker volume `workspace` контейнера `arch-docs` (`docker compose exec arch-docs` + `docker cp`, без реального `git clone` — сеть не нужна, репозитории уже локальные). Playwright-тест в `arch-docs/e2e` заполняет `InitArchForm` через UI, отслеживает прогресс через уже существующий SSE/`ConversationItemsResponse` UI, а на каждом наблюдаемом переходе шага верифицирует YAML-файл на диске контейнера через `docker compose exec arch-docs cat <path>` + парсинг через `yaml.safe_load` (Node.js `js-yaml`, так как тест в TypeScript/Playwright) и проверку известной структуры (`schema_version`, `session.current_step`, `session.completed_steps`, `session.historical_analysis.anchor_repository_name`/`current_snapshot_at` — именно эти поля показательны, так как считаются из реальной истории коммитов синтетических репозиториев в `plan_repository_order`).

**Стек:** Python 3.14 (генератор фикстур), Docker Compose (существующий `arch-docs/docker-compose.yml` + `.env.docker`), Playwright/TypeScript (существующий `arch-docs/e2e`), `js-yaml` (новая dev-зависимость e2e-пакета для парсинга YAML в тесте).

## Общие ограничения

- Никаких живых вызовов `claude`/`codex` CLI — тест не должен зависеть от реальных API-ключей и не должен зависать в ожидании настоящего LLM-ответа.
- Код и идентификаторы — на английском; комментарии/документация — на русском, только где неочевидно.
- Все новые скрипты — идемпотентны и убирают за собой (генератор фикстур можно перезапускать; e2e-тест на `afterAll`/`afterEach` подчищает поднятые сущности workspace в контейнере, чтобы повторные прогоны не копили мусор).
- Не трогать уже смерженный код фичи снепшота (`app/workflows/init_arch/snapshot.py`, `app/services/init_arch_workflow.py` и т.д.) — эта фича уже реализована, ревьюнута и запушена; этот план — только про верификацию, не про доработку.
- Docker-стек поднимается локально командой `docker compose --env-file .env.docker up -d --build` из `arch-docs/`; тест не должен сам решать, поднимать ли стек — как и у существующего `smoke.spec.ts`, предполагается, что стек уже поднят (см. `arch-docs/e2e/README.md`).
- Тест должен укладываться в разумное время (весь happy-to-interrupt путь — секунды-десятки секунд, не минуты, благодаря быстрому auth-fail вместо реального анализа).

---

## Структура файлов

- **Создать** `arch-docs/e2e/fixtures/generate-repo.sh` — генератор одного синтетического git-репозитория с историей за год по параметрам (имя, кол-во коммитов/месяц, seed-контент).
- **Создать** `arch-docs/e2e/fixtures/generate-fixture-repos.sh` — обёртка, генерирующая 3 репозитория с разным профилем истории (разные `created_at`, чтобы `plan_repository_order` детерминированно выбирал anchor).
- **Создать** `arch-docs/e2e/fixtures/README.md` — как и зачем сгенерированы фикстуры, как их пересоздать.
- **Создать** `arch-docs/e2e/helpers/docker-workspace.ts` — обёртка над `docker compose exec`/`docker cp` для (а) копирования сгенерированных репозиториев в volume `workspace` контейнера `arch-docs`, (б) чтения произвольного файла из контейнера как текста, (в) очистки тестового workspace-каталога после теста.
- **Создать** `arch-docs/e2e/helpers/snapshot-assertions.ts` — парсинг YAML снепшота (`js-yaml`) + типизированные ассершны на его форму, переиспользуемые в тесте.
- **Создать** `arch-docs/e2e/tests/init-arch-snapshot.spec.ts` — сам сценарный e2e-тест.
- **Изменить** `arch-docs/e2e/package.json` — добавить `js-yaml`+`@types/js-yaml` в devDependencies.

---

### Task 1: Генератор синтетических git-репозиториев с историей за год

**Файлы:**
- Создать: `arch-docs/e2e/fixtures/generate-repo.sh`
- Создать: `arch-docs/e2e/fixtures/generate-fixture-repos.sh`
- Создать: `arch-docs/e2e/fixtures/README.md`

**Интерфейсы:**
- `generate-repo.sh <target-dir> <repo-name> <start-date:YYYY-MM-DD> <commits-per-month>` — создаёт git-репозиторий в `<target-dir>/<repo-name>` с первым коммитом на `<start-date>` и далее `<commits-per-month>` коммитами (1 или 2) в месяц на протяжении 12 месяцев, каждый коммит меняет/добавляет файл с содержимым, зависящим от даты (чтобы `git log`/`git diff` были осмысленными, не пустыми).
- `generate-fixture-repos.sh <output-dir>` — вызывает `generate-repo.sh` три раза с тремя разными `start-date` (например, `svc-core` начиная с `2025-01-15`, `svc-billing` с `2025-03-01`, `svc-notifications` с `2025-06-10`) и разным `commits-per-month` (1, 2, 1) — так `plan_repository_order` детерминированно выберет `svc-core` как anchor (самый старый `created_at`) и это будет видно в снепшоте.

- [ ] **Шаг 1: Написать `generate-repo.sh`**

```bash
#!/usr/bin/env bash
# arch-docs/e2e/fixtures/generate-repo.sh
#
# Генерирует git-репозиторий с историей за 12 месяцев, начиная с заданной даты,
# с заданным количеством коммитов в месяц (backdated через GIT_AUTHOR_DATE/
# GIT_COMMITTER_DATE) — используется как фикстура для e2e-проверки того, что
# init_arch (refresh_main_branches/plan_repository_order) корректно читает
# created_at/историю коммитов и это отражается в progress-снепшоте.
set -euo pipefail

target_dir=$1
repo_name=$2
start_date=$3
commits_per_month=$4

repo_path="${target_dir}/${repo_name}"
rm -rf "${repo_path}"
mkdir -p "${repo_path}"
cd "${repo_path}"

git init -q -b main
git config user.name "E2E Fixture Bot"
git config user.email "e2e-fixture-bot@example.invalid"

echo "# ${repo_name}" > README.md
git add README.md
GIT_AUTHOR_DATE="${start_date}T09:00:00" GIT_COMMITTER_DATE="${start_date}T09:00:00" \
  git commit -q -m "init: scaffold ${repo_name}"

month_offset=0
while [ "${month_offset}" -lt 12 ]; do
  commit_index=1
  while [ "${commit_index}" -le "${commits_per_month}" ]; do
    commit_date=$(date -u -j -v+"${month_offset}"m -v+"${commit_index}"d -f "%Y-%m-%d" "${start_date}" +"%Y-%m-%d" 2>/dev/null \
      || date -u -d "${start_date} +${month_offset} month +${commit_index} day" +"%Y-%m-%d")
    echo "change at ${commit_date}" >> "src-${repo_name}.log"
    git add "src-${repo_name}.log"
    GIT_AUTHOR_DATE="${commit_date}T09:00:00" GIT_COMMITTER_DATE="${commit_date}T09:00:00" \
      git commit -q -m "feat(${repo_name}): change ${month_offset}-${commit_index}"
    commit_index=$((commit_index + 1))
  done
  month_offset=$((month_offset + 1))
done

echo "generated ${repo_name}: $(git -C "${repo_path}" log --oneline | wc -l | tr -d ' ') commits, first $(git -C "${repo_path}" log --reverse --format=%cd --date=short | head -1)"
```

Обрати внимание на `date` — команда неcовместима между macOS (`date -v`, BSD) и Linux (`date -d`, GNU coreutils); скрипт пробует BSD-форму первой (`||` fallback на GNU). Если оба варианта не сработают на среде, где будет реально исполняться план (проверь `uname` в начале скрипта и выведи понятную ошибку, если ни один `date` не поддерживается), — сообщи об этом в отчёте, не подгоняй скрипт вслепую под одну платформу.

- [ ] **Шаг 2: Написать `generate-fixture-repos.sh`**

```bash
#!/usr/bin/env bash
# arch-docs/e2e/fixtures/generate-fixture-repos.sh
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
output_dir=${1:-"${script_dir}/generated"}

mkdir -p "${output_dir}"

"${script_dir}/generate-repo.sh" "${output_dir}" svc-core 2025-01-15 1
"${script_dir}/generate-repo.sh" "${output_dir}" svc-billing 2025-03-01 2
"${script_dir}/generate-repo.sh" "${output_dir}" svc-notifications 2025-06-10 1

echo "fixture repos generated in ${output_dir}: svc-core (anchor, oldest created_at), svc-billing, svc-notifications"
```

- [ ] **Шаг 3: Сделать оба скрипта исполняемыми и прогнать вручную**

Команда:
```bash
cd arch-docs/e2e/fixtures
chmod +x generate-repo.sh generate-fixture-repos.sh
./generate-fixture-repos.sh /tmp/e2e-fixture-check
```
Ожидается: три каталога `/tmp/e2e-fixture-check/{svc-core,svc-billing,svc-notifications}`, каждый — валидный git-репозиторий. Проверить:
```bash
cd /tmp/e2e-fixture-check/svc-core && git log --reverse --format="%cd" --date=short | head -1
```
Ожидается: `2025-01-15` (первый коммит датирован ровно стартовой датой — это то значение, которое `refresh_main_branches` прочитает как `created_at`).

- [ ] **Шаг 4: Написать `README.md` для фикстур**

```markdown
# E2E fixture repos

Генерируются `generate-fixture-repos.sh` — три синтетических git-репозитория
с backdated-историей за 12 месяцев, использующиеся в `tests/init-arch-snapshot.spec.ts`
для проверки, что `init_arch` (`refresh_main_branches`/`plan_repository_order`)
корректно читает реальную git-историю и что это видно в `repo-initialization-progress.yaml`.

Пересоздать: `./generate-fixture-repos.sh [output-dir]` (по умолчанию `./generated`,
директория в `.gitignore` — фикстуры не коммитятся, генерируются перед прогоном e2e).

- `svc-core` — первый коммит `2025-01-15`, 1 коммит/месяц. Самый старый `created_at` →
  ожидаемый anchor repository в `plan_repository_order`.
- `svc-billing` — первый коммит `2025-03-01`, 2 коммита/месяц.
- `svc-notifications` — первый коммит `2025-06-10`, 1 коммит/месяц.
```

Добавить `arch-docs/e2e/fixtures/generated/` в `.gitignore` (проверь, есть ли уже `.gitignore` в `arch-docs/e2e/` — если нет, создай с этой одной строкой; если есть, добавь строку).

- [ ] **Шаг 5: Коммит**

```bash
cd arch-docs/e2e
git add fixtures/generate-repo.sh fixtures/generate-fixture-repos.sh fixtures/README.md .gitignore
git commit -m "test(e2e): генератор синтетических git-репозиториев с историей за год для проверки progress-снепшота"
```

---

### Task 2: Docker workspace helper — доставка фикстур в контейнер и чтение файлов из него

**Файлы:**
- Создать: `arch-docs/e2e/helpers/docker-workspace.ts`

**Интерфейсы (используется в Task 4):**
- `seedRepositoriesIntoWorkspace(runId: string, fixtureDir: string, repoNames: string[]): Promise<{ workspaceDir: string; archRepoDir: string }>` — копирует репозитории из `fixtureDir` в volume `workspace` контейнера сервиса `arch-docs` под путём `/workspace/e2e-<runId>/.temp/<repoName>` (raw layer, куда `clone_repositories` ожидает уже готовые локальные копии, если URL не указан), возвращает пути `workspaceDir`/`archRepoDir`, которые тест передаст в форму `InitArchForm`.
- `readFileFromContainer(path: string): Promise<string>` — `docker compose exec -T arch-docs cat <path>`, бросает понятную ошибку, если файла ещё нет (используется в polling-цикле теста, а не как одноразовая проверка).
- `cleanupWorkspace(runId: string): Promise<void>` — удаляет `/workspace/e2e-<runId>` из контейнера после теста.

- [ ] **Шаг 1: Проверить окружение перед реализацией**

Прочитать `arch-docs/docker-compose.yml` (сервис `arch-docs`, volume `workspace`) и `arch-docs/.env.docker`. Подтвердить, что `docker compose --env-file .env.docker up -d` из `arch-docs/` поднимает контейнер с именем сервиса `arch-docs` (не путать с именем проекта/контейнера — `docker compose exec` адресуется по имени **сервиса** из compose-файла, это `arch-docs`). Если что-то не сходится с этим описанием — не подгоняй реализацию вслепую, сообщи об этом в отчёте.

- [ ] **Шаг 2: Реализовать**

```typescript
// arch-docs/e2e/helpers/docker-workspace.ts
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";

const execFileAsync = promisify(execFile);

// Все команды выполняются относительно корня arch-docs/ (там лежит docker-compose.yml
// и .env.docker), т.к. e2e-пакет живёт в arch-docs/e2e/.
const COMPOSE_CWD = path.resolve(__dirname, "..", "..");
const COMPOSE_SERVICE = "arch-docs";

async function dockerComposeExec(args: string[]): Promise<string> {
  const { stdout } = await execFileAsync(
    "docker",
    ["compose", "--env-file", ".env.docker", "exec", "-T", COMPOSE_SERVICE, ...args],
    { cwd: COMPOSE_CWD },
  );
  return stdout;
}

export async function seedRepositoriesIntoWorkspace(
  runId: string,
  fixtureDir: string,
  repoNames: string[],
): Promise<{ workspaceDir: string; archRepoDir: string }> {
  const workspaceDir = `/workspace/e2e-${runId}`;
  const archRepoDir = `${workspaceDir}/arch-doc`;
  const rawWorkspaceDir = `${workspaceDir}/.temp`;

  await dockerComposeExec(["mkdir", "-p", rawWorkspaceDir]);

  for (const repoName of repoNames) {
    const hostRepoPath = path.join(fixtureDir, repoName);
    // docker compose cp копирует относительно текущего контейнера сервиса.
    await execFileAsync(
      "docker",
      ["compose", "--env-file", ".env.docker", "cp", hostRepoPath, `${COMPOSE_SERVICE}:${rawWorkspaceDir}/${repoName}`],
      { cwd: COMPOSE_CWD },
    );
  }

  return { workspaceDir, archRepoDir };
}

export async function readFileFromContainer(filePath: string): Promise<string> {
  try {
    return await dockerComposeExec(["cat", filePath]);
  } catch (error) {
    throw new Error(`failed to read ${filePath} from container ${COMPOSE_SERVICE}: ${String(error)}`);
  }
}

export async function cleanupWorkspace(runId: string): Promise<void> {
  await dockerComposeExec(["rm", "-rf", `/workspace/e2e-${runId}`]);
}
```

- [ ] **Шаг 3: Написать и прогнать ручную проверку (не Playwright-тест — просто скрипт-скретч, стек должен быть поднят)**

Убедиться, что стек поднят (`cd arch-docs && docker compose --env-file .env.docker up -d --build`), затем из `arch-docs/e2e`:
```bash
node -e "
const { seedRepositoriesIntoWorkspace, readFileFromContainer, cleanupWorkspace } = require('./helpers/docker-workspace.ts');
"
```
Так как файл в TypeScript без сборки — проверить через `npx tsx` или аналогичный доступный в `package.json` раннер (посмотри, что уже используется в проекте для отдельных TS-скриптов; если ничего нет — временно проверь логику через `ts-node`/`tsx` как dev-инструмент, но не добавляй его в зависимости, если для финального теста он не нужен — Playwright сам компилирует `.spec.ts`, этот helper будет импортирован оттуда, а не запущен отдельно в финальной версии). Главное — вручную убедиться, что `docker compose cp`/`exec` из этого хелпера реально доставляет один тестовый файл в контейнер и читает его обратно, прежде чем полагаться на это в Task 4.

- [ ] **Шаг 4: Коммит**

```bash
cd arch-docs/e2e
git add helpers/docker-workspace.ts
git commit -m "test(e2e): helper для доставки фикстур в docker workspace и чтения файлов из контейнера"
```

---

### Task 3: YAML snapshot assertions helper

**Файлы:**
- Создать: `arch-docs/e2e/helpers/snapshot-assertions.ts`
- Изменить: `arch-docs/e2e/package.json` (добавить `js-yaml`, `@types/js-yaml` в devDependencies)

**Интерфейсы (используется в Task 4):**
- `parseSnapshotYaml(yamlText: string): WorkflowSnapshotShape` — парсит YAML через `js-yaml`, возвращает типизированный объект.
- `WorkflowSnapshotShape` — TypeScript-тип, зеркалящий поля `WorkflowSnapshot` из `arch-docs/back/app/workflows/init_arch/snapshot.py` (`schema_version`, `workflow_id`, `workspace_dir`, `arch_repo_dir`, `engine_name`, `timeout_seconds`, `updated_at`, `session` с вложенными `current_step`, `completed_steps`, `repositories`, `historical_analysis`).

- [ ] **Шаг 1: Добавить зависимость**

Команда: `cd arch-docs/e2e && npm install --save-dev js-yaml @types/js-yaml`

- [ ] **Шаг 2: Прочитать реальную структуру `WorkflowSnapshot` перед реализацией типа**

Открыть `arch-docs/back/app/workflows/init_arch/snapshot.py` и `arch-docs/back/app/workflows/init_arch/domain/models.py` (`WorkflowSessionRecord`, `HistoricalAnalysisState`, `RepositoryExecution`) — скопировать реальные имена полей 1:1, не придумывай поля по памяти из этого плана, сверься с актуальным кодом (эта фича уже смержена в main-ветку сервиса на момент выполнения этого плана).

- [ ] **Шаг 3: Реализовать**

```typescript
// arch-docs/e2e/helpers/snapshot-assertions.ts
import yaml from "js-yaml";

export interface RepositoryExecutionShape {
  repository_name: string;
  created_at: string | null;
  main_branch: string;
  analysis_status: string;
}

export interface HistoricalAnalysisShape {
  anchor_repository_name: string;
  anchor_created_at: string | null;
  current_snapshot_at: string | null;
  ordered_repository_names: string[];
}

export interface WorkflowSessionShape {
  session_id: string;
  current_step: string;
  completed_steps: string[];
  repositories: RepositoryExecutionShape[];
  historical_analysis: HistoricalAnalysisShape;
}

export interface WorkflowSnapshotShape {
  schema_version: number;
  workflow_id: string;
  workspace_dir: string;
  arch_repo_dir: string;
  engine_name: string;
  timeout_seconds: number;
  updated_at: string;
  session: WorkflowSessionShape;
}

export function parseSnapshotYaml(yamlText: string): WorkflowSnapshotShape {
  const parsed = yaml.load(yamlText);
  if (typeof parsed !== "object" || parsed === null) {
    throw new Error(`snapshot YAML did not parse to an object: ${yamlText.slice(0, 200)}`);
  }
  return parsed as WorkflowSnapshotShape;
}
```

Не добавляй сюда сами `expect(...)`-проверки — этот файл только парсит и типизирует, конкретные ассершны по сценарию — в самом тесте (Task 4), так у helper остаётся одна ответственность.

- [ ] **Шаг 4: Прогнать typecheck**

Команда: `cd arch-docs/e2e && npx tsc --noEmit` (или существующий npm-скрипт для typecheck, если есть в `package.json` — проверь сначала). Ожидается: без ошибок.

- [ ] **Шаг 5: Коммит**

```bash
cd arch-docs/e2e
git add package.json package-lock.json helpers/snapshot-assertions.ts
git commit -m "test(e2e): helper для парсинга и типизации WorkflowSnapshot YAML"
```

---

### Task 4: Сценарный e2e-тест — init_arch через UI до interrupt, проверка снепшота на каждом шаге

**Файлы:**
- Создать: `arch-docs/e2e/tests/init-arch-snapshot.spec.ts`

**Интерфейсы:** использует `seedRepositoriesIntoWorkspace`/`readFileFromContainer`/`cleanupWorkspace` (Task 2), `parseSnapshotYaml` (Task 3), фикстуры из `fixtures/generate-fixture-repos.sh` (Task 1, запускается в `beforeAll`).

- [ ] **Шаг 1: Прочитать перед реализацией**

Открой `arch-docs/front/src/features/workflow/init-arch-form.tsx`, `init-workflow-start-page.tsx`, `hooks.ts` и `arch-docs/e2e/tests/smoke.spec.ts` — тест должен взаимодействовать с реальными полями формы (`productName`, `repoList`, `workspaceDir`, `archRepoDir`, `engineName`) через их видимые label/placeholder, а не угадывать селекторы. Если реальная разметка формы отличается от того, что описано в этом плане (поля могли измениться) — ориентируйся на актуальный код компонента, не на этот текст.

Также открой `arch-docs/back/app/services/task_runner.py` (`_CLAUDE_AUTH_ERROR_SUBSTRINGS`, `FAILURE_REASON_AUTH_EXPIRED`) и `arch-docs/back/app/workflows/init_arch/nodes.py` (`_MAX_RETRY`, retry-логика в `_simple_llm_step`/graph-level routing) — чтобы понимать, сколько раз и как быстро `clone_repositories` уйдёт в `handle_error` без авторизации, и не закладывать в тест предположения о таймингах, которые не подтверждены чтением кода.

- [ ] **Шаг 2: Сгенерировать фикстуры перед прогоном (не в тесте, отдельным `beforeAll`, вызывающим shell-скрипт)**

```typescript
// arch-docs/e2e/tests/init-arch-snapshot.spec.ts
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { cleanupWorkspace, readFileFromContainer, seedRepositoriesIntoWorkspace } from "../helpers/docker-workspace";
import { parseSnapshotYaml } from "../helpers/snapshot-assertions";

const execFileAsync = promisify(execFile);
const FIXTURES_DIR = path.resolve(__dirname, "..", "fixtures");
const GENERATED_DIR = path.join(FIXTURES_DIR, "generated");
const REPO_NAMES = ["svc-core", "svc-billing", "svc-notifications"];

test.describe("init_arch: progress-снепшот через реальный docker-стек", () => {
  test.setTimeout(120_000);

  let runId: string;
  let workspaceDir: string;
  let archRepoDir: string;

  test.beforeAll(async () => {
    await execFileAsync(path.join(FIXTURES_DIR, "generate-fixture-repos.sh"), [GENERATED_DIR]);
  });

  test.beforeEach(async () => {
    runId = `snap-${Date.now()}`;
    const seeded = await seedRepositoriesIntoWorkspace(runId, GENERATED_DIR, REPO_NAMES);
    workspaceDir = seeded.workspaceDir;
    archRepoDir = seeded.archRepoDir;
  });

  test.afterEach(async () => {
    await cleanupWorkspace(runId);
  });

  test("снепшот отражает реальный прогресс до interrupt на clone_repositories", async ({ page }) => {
    // Шаги 3-6 заполняются далее
  });
});
```

- [ ] **Шаг 3: Реализовать заполнение формы и старт workflow через UI**

Внутри теста из Шага 2:
```typescript
    await page.goto("/setup");
    // TODO(implementer): дойти до страницы старта init_arch по реальной навигации SPA
    // (посмотри init-workflow-start-page.tsx/роутинг — какая кнопка/ссылка туда ведёт).
    // Заполнить форму: productName = "E2E Snapshot Check", repoList = REPO_NAMES (без URL —
    // репозитории уже лежат в raw_workspace_dir через seedRepositoriesIntoWorkspace),
    // workspaceDir = workspaceDir, archRepoDir = archRepoDir, engineName = "claude"
    // (или что доступно в форме по умолчанию — не критично, живой вызов всё равно не пройдёт).
    // Сабмитнуть форму.
```

Реализуй это по-настоящему (заменив комментарий-заглушку выше реальным Playwright-кодом) — маршрут `/setup → запуск init_arch` в этом плане описан только по названиям файлов, точную последовательность кликов/полей нужно установить чтением актуального фронтенд-кода из Шага 1, а не изобретать. Если навигация до формы неочевидна из кода — предпочти явный `page.goto()` на конкретный маршрут (посмотри роутер, например `App.tsx`/`router.tsx`), а не цепочку кликов, если оба варианта доступны — так тест устойчивее к изменениям в другом месте UI.

- [ ] **Шаг 4: Дождаться прогресса через детерминированные шаги и проверить снепшот на каждом**

```typescript
    const observedSteps: string[] = [];
    const deadline = Date.now() + 90_000;

    while (Date.now() < deadline) {
      let snapshotText: string;
      try {
        snapshotText = await readFileFromContainer(`${archRepoDir}/repo-initialization-progress.yaml`);
      } catch {
        await page.waitForTimeout(1_000);
        continue;
      }
      const snapshot = parseSnapshotYaml(snapshotText);
      if (!observedSteps.includes(snapshot.session.current_step)) {
        observedSteps.push(snapshot.session.current_step);
      }
      // Останавливаемся, когда граф дошёл до handle_error / retry-цикла на clone_repositories
      // и больше не продвигается — если current_step остаётся "clone_repositories" достаточно
      // долго (несколько последовательных чтений без изменений), считаем, что дошли до interrupt.
      if (snapshot.session.current_step === "clone_repositories" && observedSteps.filter((s) => s === "clone_repositories").length > 2) {
        break;
      }
      await page.waitForTimeout(1_000);
    }

    // Прошли реально хотя бы через детерминированные шаги до clone_repositories.
    expect(observedSteps).toContain("request_repository_list");
    expect(observedSteps).toContain("prepare_temp_workspace");
```

Уточни у себя перед реализацией (по факту чтения `graph.py`/`nodes.py` из Шага 1), какие именно значения `current_step` реально проходятся между `prepare_temp_workspace` и `clone_repositories` — в частности, значится ли в снепшоте промежуточный `refresh_main_branches`/`plan_repository_order` ДО того, как дойдёт до первого реального LLM-шага, или порядок графа иной (сверься с `_LINEAR_STEP_IDS`/`STEP_DEFINITIONS`, не с этим планом — граф мог быть немного другим на момент выполнения). Скорректируй список ожидаемых `toContain(...)` по тому, что реально увидишь в первом ручном прогоне, а не по домыслу.

- [ ] **Шаг 5: Проверить финальное состояние снепшота (после исчерпания ретраев на clone_repositories)**

```typescript
    const finalSnapshotText = await readFileFromContainer(`${archRepoDir}/repo-initialization-progress.yaml`);
    const finalSnapshot = parseSnapshotYaml(finalSnapshotText);

    expect(finalSnapshot.schema_version).toBe(1);
    expect(finalSnapshot.workspace_dir).toBe(workspaceDir);
    expect(finalSnapshot.arch_repo_dir).toBe(archRepoDir);
    expect(finalSnapshot.session.completed_steps).toContain("prepare_temp_workspace");

    // plan_repository_order успевает отработать до clone_repositories? Проверь порядок графа
    // (см. примечание в Шаге 4) — если historical_analysis заполняется ДО первого LLM-шага,
    // проверь его здесь; если он заполняется ПОСЛЕ clone_repositories (значит на этом прогоне
    // без живого LLM он не заполнится вовсе) — этот блок нужно убрать или перенести проверку
    // anchor_repository_name на отдельный тест, который доходит только до того места, где
    // это поле реально успевает выставиться. Не выдумывай ожидаемое значение — сверься с графом.
```

- [ ] **Шаг 6: Прогнать тест против реально поднятого стека**

Предпосылка (как и для `smoke.spec.ts`):
```bash
cd arch-docs && docker compose --env-file .env.docker up -d --build
```
Затем:
```bash
cd arch-docs/e2e
npx playwright test tests/init-arch-snapshot.spec.ts
```
Ожидается: тест проходит за разумное время (без реальных LLM-вызовов путь должен занимать десятки секунд, не минуты — если auth-фейл на `clone_repositories` неожиданно долгий/зависает, это находка для отчёта, не то, что нужно "перетерпеть" увеличением таймаутов вслепую).

Если тест падает — прочитай логи контейнера (`docker compose --env-file .env.docker -f ../docker-compose.yml logs arch-docs --tail 200`, путь скорректируй под реальный cwd) прежде чем менять тест — причина может быть в самом стеке (например, отсутствующие переменные окружения), а не в тесте.

- [ ] **Шаг 7: Коммит**

```bash
cd arch-docs/e2e
git add tests/init-arch-snapshot.spec.ts
git commit -m "test(e2e): сценарный тест progress-снепшота через реальный docker-стек до interrupt на clone_repositories"
```

---

## Самопроверка

**Покрытие:**
- «3 локальных тестовых репозитория с имитацией истории за год (1-2 коммита/месяц)» → Task 1.
- «e2e с поднятым фронтом+беком в докере» → Task 4, реально управляет UI через Playwright против `docker compose` стека.
- «отладить и проверить корректность сформированных файлов» → Task 4, Шаги 4-5 проверяют реальный YAML на диске контейнера на каждом наблюдаемом переходе.
- Явно НЕ покрыто (по согласованному скоупу): resume через браузер (недоступно через UI, только MCP), полный анализ с реальными LLM-вызовами.

**Скан на плейсхолдеры:** два места в Task 4 (Шаг 3 первая половина, Шаг 4/5 списки ожидаемых шагов) намеренно оставлены как "сверься с актуальным кодом перед тем как писать точные ассершны", а не как "TBD/implement later" — план сознательно не может знать точный порядок графа/точную разметку формы без чтения кода на момент исполнения; это методологическое указание имплементору, а не недоделанный шаг плана. Если это неприемлемо — обсудить с человеком до старта Task 4.

**Согласованность типов:** `seedRepositoriesIntoWorkspace`/`readFileFromContainer`/`cleanupWorkspace` (Task 2) используются в Task 4 с теми же именами и сигнатурами. `parseSnapshotYaml`/`WorkflowSnapshotShape` (Task 3) используются в Task 4 идентично.
