import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";
import {
  buildTestProjectName,
  purgeTestProjectsBestEffort,
  renameConversation,
  renameProjectCreatedInUi,
} from "../helpers/test-projects";

// Покрывает новый функционал спеки 2026-07-23-per-workflow-workspace-and-browser.md:
// - "Проекты" вместо "Init Workflow" (раздел 4);
// - репозитории/название как настройка conversation, а не отдельного run (раздел 2-3);
// - лимит "максимум 1 активный init_arch на conversation" (раздел "Инвариант");
// - picker проекта на вкладке Docs (раздел 6).
//
// Запускаются последовательно (не fullyParallel) - nginx rate-limit (`api_limit`, 300r/m burst 60,
// см. nginx-templates/default.conf.template) рассчитан на одного реального пользователя, а не на
// N параллельных воркеров, каждый из которых создаёт conversation/repositories/responses в одном
// коротком окне.
test.describe.configure({ mode: "serial" });

// Тот же burst разделяется всеми тестами файла (serial + один nginx-инстанс) - небольшая пауза перед
// каждым тестом даёт токенам частично восстановиться (5 токенов/с), иначе несколько ProjectPage подряд
// (4 параллельных GET на маунт каждая) могут исчерпать burst.
test.beforeEach(async () => {
  await new Promise((resolve) => setTimeout(resolve, 3_000));
});

test.afterEach(async ({ request }) => {
  await purgeTestProjectsBestEffort(request);
});

async function createConversation(request: APIRequestContext): Promise<string> {
  const resp = await request.post("/api/rest/conversations/");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  const conversationId = body.conversation_id as string;
  const productName = buildTestProjectName(`project ${conversationId}`);
  await renameConversation(request, conversationId, productName);
  return conversationId;
}

test.describe("Проекты: список и страница проекта", () => {
  test("роут /projects отдаёт SPA с заголовком «Проекты» и рабочей навигацией", async ({ page }) => {
    const response = await page.goto("/projects");
    expect(response?.status()).toBe(200);
    await expect(page.locator("h1")).toHaveText("Проекты");
    await expect(page.getByRole("link", { name: "Проекты" })).toHaveAttribute("aria-current", "page");
  });

  test("создание проекта ведёт на /projects/:conversationId с тремя колонками", async ({ page, request }) => {
    await page.goto("/projects");
    await page.getByRole("button", { name: "Создать проект" }).click();
    await renameProjectCreatedInUi(page, request, `ui-created-project ${Date.now()}`);

    await expect(page.getByText("Репозитории проекта")).toBeVisible();
    await expect(page.getByText("Файлы проекта")).toBeVisible();
    await expect(page.getByText("Содержимое")).toBeVisible();
    await expect(page.getByText("Workflow")).toBeVisible();
  });

  test("репозитории проекта добавляются и удаляются из левой колонки, без запуска workflow", async ({
    page,
    request,
  }) => {
    const conversationId = await createConversation(request);
    await page.goto(`/projects/${conversationId}`);

    const repoInput = page.getByPlaceholder("URL или имя репозитория");
    const addButton = page.getByRole("button", { name: "Добавить" });

    await repoInput.fill("svc-alpha");
    await addButton.click();
    await expect(page.getByText("svc-alpha", { exact: true })).toBeVisible();

    await repoInput.fill("svc-beta");
    await addButton.click();
    await expect(page.getByText("svc-beta", { exact: true })).toBeVisible();

    // Список репозиториев проекта персистентный (настройка conversation в БД, раздел 2 спеки), а не
    // эфемерное клиентское состояние формы - проверяем это через REST напрямую, не перезагружая
    // страницу (лишний полный remount добавляет ещё 3-4 запроса и приближает nginx rate-limit).
    const persisted = await request.get(`/api/rest/conversations/${conversationId}/repositories/`);
    expect((await persisted.json()).map((r: { repository_name: string }) => r.repository_name)).toEqual([
      "svc-alpha",
      "svc-beta",
    ]);

    // Название репозитория лежит в .info внутри .row (единый список репозиториев проекта,
    // обогащаемый данными коммитов из выбранного прогона, см. ConversationRepositories) - до
    // строки с кнопкой "Удалить" нужно подняться на два div, а не на один.
    const alphaRow = page.getByText("svc-alpha", { exact: true }).locator("xpath=ancestor::div[2]");
    await alphaRow.getByRole("button", { name: "Удалить" }).click();
    await expect(page.getByText("svc-alpha", { exact: true })).not.toBeVisible();
    await expect(page.getByText("svc-beta", { exact: true })).toBeVisible();
  });

  test("проект без репозиториев не позволяет запустить init_arch", async ({ page, request }) => {
    const conversationId = await createConversation(request);
    await page.goto(`/projects/${conversationId}`);

    await page.getByRole("button", { name: "Запустить" }).click();
    await page.getByRole("button", { name: "Запустить init_arch" }).click();

    await expect(page.getByText("Добавьте хотя бы один репозиторий проекта в колонке слева.")).toBeVisible();
  });
});

test.describe("Инвариант: максимум один активный init_arch на conversation", () => {
  test("второй POST /responses/ для той же conversation с уже активным init_arch возвращает 409", async ({
    request,
  }) => {
    const conversationId = await createConversation(request);
    await request.post(`/api/rest/conversations/${conversationId}/repositories/`, {
      data: { entry: "svc-guard" },
    });

    const buildInput = () => ({
      conversation_id: conversationId,
      workflow_type: "init_arch",
      input: {
        product_name: buildTestProjectName("Guard Check"),
        analysis_scope: "full",
        workspace_dir: `/workspace/${conversationId}`,
        arch_repo_dir: `/workspace/${conversationId}/arch-doc`,
        engine_name: "claude",
        timeout_seconds: 15,
      },
    });

    const first = await request.post("/api/rest/responses/", { data: buildInput() });
    expect(first.status()).toBe(202);

    const second = await request.post("/api/rest/responses/", { data: buildInput() });
    expect(second.status()).toBe(409);
  });
});

test.describe("Docs: picker проекта", () => {
  test("вкладка Docs предлагает выбрать проект по названию вместо ручного response_id", async ({
    page,
    request,
  }) => {
    // Уникальное имя на прогон - conversations в БД не чистятся между запусками e2e-сьюта, а
    // ProjectPicker матчит по точному тексту кнопки, так что повторный прогон с фиксированным
    // именем со временем ловит strict-mode violation на несколько одноимённых проектов.
    const productName = buildTestProjectName(`Docs Picker Project ${Date.now()}`);
    const conversationId = await createConversation(request);
    await renameConversation(request, conversationId, productName);
    await request.post(`/api/rest/conversations/${conversationId}/repositories/`, {
      data: { entry: "svc-docs" },
    });

    const createResponse = await request.post("/api/rest/responses/", {
      data: {
        conversation_id: conversationId,
        workflow_type: "init_arch",
        input: {
          product_name: productName,
          analysis_scope: "full",
          workspace_dir: `/workspace/${conversationId}`,
          arch_repo_dir: `/workspace/${conversationId}/arch-doc`,
          engine_name: "claude",
          timeout_seconds: 15,
        },
      },
    });
    expect(createResponse.status()).toBe(202);

    await page.goto("/docs");
    const projectButton = page.getByRole("tab", { name: productName });
    await expect(projectButton).toBeVisible();
    await projectButton.click();

    // arch_repo_dir существует (создан на prepare_temp_workspace), пусть и пустой - дерево должно
    // отрисоваться без ошибки, а не остаться на экране ручного ввода response_id.
    await expect(page.getByText(/укажите response_id/i)).not.toBeVisible();
  });
});
