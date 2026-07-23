import { HttpResponse, http } from "msw";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { server } from "../../test/msw-server";
import { renderWithProviders } from "../../test/render";
import { DocsPage } from "./docs-page";

const TREE_RESPONSE = {
  path: "",
  name: "root",
  node_type: "directory" as const,
  size: 0,
  modified_at: "2026-07-01T00:00:00Z",
  media_kind: null,
  children: [
    {
      path: "README.md",
      name: "README.md",
      node_type: "file" as const,
      size: 42,
      modified_at: "2026-07-01T00:00:00Z",
      media_kind: "markdown" as const,
      children: null,
    },
  ],
};

describe("DocsPage", () => {
  it("открывает файл из дерева и рендерит markdown", async () => {
    server.use(
      http.get("/api/rest/conversations/conv-1/workspace/tree/", () => HttpResponse.json(TREE_RESPONSE)),
      http.get("/api/rest/conversations/conv-1/workspace/file/", ({ request }) => {
        const path = new URL(request.url).searchParams.get("path");
        expect(path).toBe("README.md");
        return HttpResponse.json({
          path: "README.md",
          name: "README.md",
          media_kind: "markdown",
          content: "# Заголовок\n\nТекст документа",
          encoding: "utf-8",
          size: 42,
          modified_at: "2026-07-01T00:00:00Z",
        });
      }),
    );

    renderWithProviders(<DocsPage />, { route: "/docs?conversationId=conv-1" });

    const fileButton = await screen.findByRole("button", { name: /README\.md/ });
    await userEvent.click(fileButton);

    expect(await screen.findByRole("heading", { name: "Заголовок" })).toBeInTheDocument();
  });

  it("предлагает ввести id проекта, если он не передан и не сохранён", async () => {
    server.use(http.get("/api/rest/conversations/", () => HttpResponse.json([])));
    renderWithProviders(<DocsPage />);
    expect(await screen.findByText(/укажите id проекта/i)).toBeInTheDocument();
  });

  it("предлагает выбрать проект из picker и открывает его дерево файлов", async () => {
    server.use(
      http.get("/api/rest/conversations/", () =>
        HttpResponse.json([
          {
            conversation_id: "conv-1",
            product_name: "Arch Docs Gateway",
            repositories: [],
            workspace_dir: "/workspace/conv-1",
            created_at: "2026-07-01T00:00:00Z",
            updated_at: "2026-07-01T00:00:00Z",
            active_response: null,
            previous_init_input: null,
          },
        ]),
      ),
      http.get("/api/rest/conversations/conv-1/workspace/tree/", () => HttpResponse.json(TREE_RESPONSE)),
    );

    renderWithProviders(<DocsPage />);

    const projectButton = await screen.findByRole("tab", { name: "Arch Docs Gateway" });
    await userEvent.click(projectButton);

    expect(await screen.findByRole("button", { name: /README\.md/ })).toBeInTheDocument();
  });
});
