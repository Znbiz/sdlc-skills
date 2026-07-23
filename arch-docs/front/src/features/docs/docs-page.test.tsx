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
      http.get("/api/rest/responses/resp-1/docs/tree/", () => HttpResponse.json(TREE_RESPONSE)),
      http.get("/api/rest/responses/resp-1/docs/file/", ({ request }) => {
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

    renderWithProviders(<DocsPage />, { route: "/docs?responseId=resp-1" });

    const fileButton = await screen.findByRole("button", { name: /README\.md/ });
    await userEvent.click(fileButton);

    expect(await screen.findByRole("heading", { name: "Заголовок" })).toBeInTheDocument();
  });

  it("предлагает ввести response_id, если он не передан и не сохранён", async () => {
    server.use(http.get("/api/rest/conversations/", () => HttpResponse.json([])));
    renderWithProviders(<DocsPage />);
    expect(await screen.findByText(/укажите response_id/i)).toBeInTheDocument();
  });

  it("предлагает выбрать проект из picker и открывает его последний run", async () => {
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
            active_response: {
              response_id: "resp-1",
              conversation_id: "conv-1",
              workflow_type: "init_arch",
              response_status: "success",
              current_step_id: "done",
              current_repo_name: "",
              workspace_dir: "/workspace/conv-1",
              arch_repo_dir: "/workspace/conv-1/arch-doc",
              completed_steps: [],
              required_actions: [],
              repositories: [],
              repository_list_editable: false,
              created_at: "2026-07-01T00:00:00Z",
              updated_at: "2026-07-01T00:00:00Z",
              error_message: null,
              terminal_result: null,
            },
            previous_init_input: null,
          },
        ]),
      ),
      http.get("/api/rest/responses/resp-1/docs/tree/", () => HttpResponse.json(TREE_RESPONSE)),
    );

    renderWithProviders(<DocsPage />);

    const projectButton = await screen.findByRole("tab", { name: "Arch Docs Gateway" });
    await userEvent.click(projectButton);

    expect(await screen.findByRole("button", { name: /README\.md/ })).toBeInTheDocument();
  });
});
