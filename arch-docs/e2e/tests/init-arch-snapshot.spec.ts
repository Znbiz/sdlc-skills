import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { cleanupWorkspace, readFileFromContainer, seedRepositoriesIntoWorkspace } from "../helpers/docker-workspace";
import { parseSnapshotYaml } from "../helpers/snapshot-assertions";

const execFileAsync = promisify(execFile);
const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = path.resolve(MODULE_DIR, "..", "fixtures");
const GENERATED_DIR = path.join(FIXTURES_DIR, "generated");
const REPO_NAMES = ["svc-core", "svc-billing", "svc-notifications"];

// Держим таймаут шага низким: без валидной авторизации claude/codex каждый повтор
// clone_repositories всё равно упадёт (auth-ошибка или любой ненулевой exit-code),
// а _MAX_RETRY=3 в graph.py даёт максимум 3 попытки перед routing в handle_error.
// 15 секунд * 3 попытки ограничивают худший случай (если CLI зависает), не растягивая тест.
const STEP_TIMEOUT_SECONDS = 15;

// Детерминированные шаги графа (uses_llm_worker=False в steps.py) до первого LLM-шага.
// clone_repositories — первый LLM-шаг; без авторизации он не проходит и current_step
// остаётся на нём. refresh_main_branches/plan_repository_order (где заполняется
// historical_analysis) идут ПОСЛЕ clone_repositories, поэтому в этом прогоне не выполняются.
const DETERMINISTIC_COMPLETED_STEPS = ["define_scope", "request_repository_list", "prepare_temp_workspace"];

test.describe("init_arch: progress-снепшот через реальный docker-стек", () => {
  test.setTimeout(180_000);

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
    // Шаг 3: реальная навигация SPA + заполнение формы.
    // /workflows/init → создать conversation → редирект на /workflows/init/:conversationId,
    // где InitWorkflowPage рендерит InitArchForm (пока нет active_response).
    await page.goto("/workflows/init");
    await page.getByRole("button", { name: "Создать conversation" }).click();
    await page.waitForURL(/\/workflows\/init\/.+/);

    // Название продукта (input с placeholder "Arch Docs Gateway").
    await page.getByPlaceholder("Arch Docs Gateway").fill("E2E Snapshot Check");

    // Репозитории: одна строка по умолчанию, добавляем ещё две и заполняем все три
    // именами (без URL) — репозитории уже засеяны в raw_workspace_dir (.temp).
    const addRepoButton = page.getByRole("button", { name: "Добавить репозиторий" });
    await addRepoButton.click();
    await addRepoButton.click();
    const repoInputs = page.getByPlaceholder("https://github.com/org/repo.git");
    await expect(repoInputs).toHaveCount(REPO_NAMES.length);
    for (let index = 0; index < REPO_NAMES.length; index += 1) {
      await repoInputs.nth(index).fill(REPO_NAMES[index]);
    }

    // Движок: claude (дефолт формы). Живой вызов всё равно не пройдёт без авторизации.
    await page.getByLabel("Движок").selectOption("claude");

    // Таймаут шага держим низким, чтобы повторы clone_repositories не растягивались.
    await page.getByLabel("Таймаут шага, сек").fill(String(STEP_TIMEOUT_SECONDS));

    // Advanced: workspace_dir / arch_repo_dir лежат внутри <details>, раскрываем.
    await page.locator("summary", { hasText: "Advanced" }).click();
    await page.getByLabel("Workspace dir").fill(workspaceDir);
    await page.getByLabel("Arch repo dir").fill(archRepoDir);

    await page.getByRole("button", { name: "Запустить init_arch" }).click();

    // Форма сменилась на карточку статуса — значит workflow создан и запущен.
    await expect(page.getByText("Текущий статус")).toBeVisible({ timeout: 30_000 });

    // Шаг 4: ждём, пока снепшот на диске контейнера дойдёт до clone_repositories.
    // Это терминальное состояние current_step для данного прогона: без авторизации
    // clone_repositories не проходит и граф не продвигается дальше.
    const progressPath = `${archRepoDir}/repo-initialization-progress.yaml`;
    const observedSteps: string[] = [];
    const deadline = Date.now() + 150_000;
    let cloneSnapshot: ReturnType<typeof parseSnapshotYaml> | undefined;

    while (Date.now() < deadline) {
      let snapshotText: string;
      try {
        snapshotText = await readFileFromContainer(progressPath);
      } catch {
        await page.waitForTimeout(1_000);
        continue;
      }
      const snapshot = parseSnapshotYaml(snapshotText);
      const currentStep = snapshot.session.current_step ?? "";
      if (!observedSteps.includes(currentStep)) {
        observedSteps.push(currentStep);
      }
      if (currentStep === "clone_repositories") {
        cloneSnapshot = snapshot;
        break;
      }
      await page.waitForTimeout(1_000);
    }

    expect(cloneSnapshot, `snapshot не дошёл до clone_repositories; наблюдались шаги: ${observedSteps.join(", ")}`).toBeTruthy();
    const snapshot = cloneSnapshot!;

    // Шаг 5: проверяем реальное содержимое снепшота на диске контейнера.
    // Топ-левел метаданные снепшота (см. WorkflowSnapshot в snapshot.py).
    expect(snapshot.schema_version).toBe(1);
    expect(snapshot.workspace_dir).toBe(workspaceDir);
    expect(snapshot.arch_repo_dir).toBe(archRepoDir);
    expect(snapshot.engine_name).toBe("claude");
    expect(snapshot.timeout_seconds).toBe(STEP_TIMEOUT_SECONDS);

    // Сессия: продукт и текущий шаг.
    expect(snapshot.session.product_name).toBe("E2E Snapshot Check");
    expect(snapshot.session.current_step).toBe("clone_repositories");

    // Детерминированные шаги реально завершились до первого LLM-шага (append-only список).
    const completedSteps = snapshot.session.completed_steps ?? [];
    for (const step of DETERMINISTIC_COMPLETED_STEPS) {
      expect(completedSteps).toContain(step);
    }
    // clone_repositories не завершился (упал), поэтому его нет в completed_steps.
    expect(completedSteps).not.toContain("clone_repositories");
    // historical_analysis заполняется на refresh_main_branches/plan_repository_order,
    // которые идут ПОСЛЕ clone_repositories и в этом прогоне не выполняются.
    expect(completedSteps).not.toContain("refresh_main_branches");
    expect(completedSteps).not.toContain("plan_repository_order");

    // Репозитории из формы попали в сессию и ещё не анализировались.
    const repositoryNames = (snapshot.session.repositories ?? []).map((repo) => repo.repository_name);
    expect(repositoryNames).toEqual(REPO_NAMES);
    for (const repo of snapshot.session.repositories ?? []) {
      expect(repo.analysis_status ?? "pending").toBe("pending");
    }

    // historical_analysis не заполнен (anchor определяется только на refresh_main_branches).
    const historical = snapshot.session.historical_analysis ?? {};
    expect(historical.anchor_repository_name ?? "").toBe("");
    expect(historical.ordered_repository_names ?? []).toEqual([]);

    // Шаг 6: подтверждаем, что прогон реально дошёл до ожидаемого interrupt через UI —
    // после исчерпания повторов clone_repositories граф уходит в handle_error (step_failed),
    // и на странице появляется карточка "Требуется действие" с сообщением об ошибке шага.
    await expect(page.getByText(/завершился ошибкой/)).toBeVisible({ timeout: 120_000 });
    await expect(page.getByText("step_id: clone_repositories")).toBeVisible();
  });
});
