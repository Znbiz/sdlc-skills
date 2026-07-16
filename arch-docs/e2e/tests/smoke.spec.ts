import { expect, test } from "@playwright/test";

test.describe("smoke: nginx отдаёт SPA и проксирует backend", () => {
  test("корень отдаёт SPA с ожидаемым title", async ({ page }) => {
    const response = await page.goto("/");
    expect(response?.status()).toBe(200);
    await expect(page).toHaveTitle(/arch-docs/);
  });

  test("клиентский route /setup работает через SPA fallback", async ({ page }) => {
    const response = await page.goto("/setup");
    expect(response?.status()).toBe(200);
    await expect(page.locator("h1")).toHaveText("Setup");
  });

  test("backend доступен через OpenAI-facade /v1/models", async ({ request }) => {
    const response = await request.get("/v1/models");
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(Array.isArray(body.data)).toBe(true);
  });
});
