import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const TEST_PROJECT_PREFIX = "test-";

type ConversationSummary = {
  conversation_id: string;
  product_name: string | null;
};

type RequestLike = Pick<APIRequestContext, "get" | "delete">;

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-");
}

export function buildTestProjectName(baseName: string): string {
  const slug = slugify(baseName);
  return slug ? `${TEST_PROJECT_PREFIX}${slug}` : `${TEST_PROJECT_PREFIX}project`;
}

export async function renameConversation(
  request: APIRequestContext,
  conversationId: string,
  productName: string,
): Promise<void> {
  const patchResp = await request.patch(`/api/rest/conversations/${conversationId}/`, {
    data: { product_name: productName },
  });
  expect(patchResp.ok()).toBeTruthy();
}

export async function renameProjectCreatedInUi(
  page: Page,
  request: APIRequestContext,
  baseName: string,
): Promise<{ conversationId: string; productName: string }> {
  await page.waitForURL(/\/projects\/[^/]+$/);
  const conversationId = page.url().split("/").at(-1) ?? "";
  expect(conversationId).toBeTruthy();
  const productName = buildTestProjectName(baseName);
  await renameConversation(request, conversationId, productName);
  await page.reload();
  return { conversationId, productName };
}

export async function purgeTestProjects(request: RequestLike): Promise<void> {
  const listResp = await request.get("/api/rest/conversations/", { params: { limit: 200 } });
  if (!listResp.ok()) {
    throw new Error(`failed to list conversations for purge: ${listResp.status()}`);
  }

  const conversations = (await listResp.json()) as ConversationSummary[];
  for (const conversation of conversations) {
    if (!conversation.product_name?.startsWith(TEST_PROJECT_PREFIX)) continue;
    const deleteResp = await request.delete(`/api/rest/conversations/${conversation.conversation_id}/`);
    if (![204, 404].includes(deleteResp.status())) {
      throw new Error(
        `failed to delete test conversation ${conversation.conversation_id}: ${deleteResp.status()}`,
      );
    }
  }
}

export async function purgeTestProjectsBestEffort(request: RequestLike): Promise<void> {
  try {
    await purgeTestProjects(request);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message.includes("connect EPERM") || message.includes("ECONNREFUSED") || message.includes("ENOTFOUND")) {
      return;
    }
    throw error;
  }
}
