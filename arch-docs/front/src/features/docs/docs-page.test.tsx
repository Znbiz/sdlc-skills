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
    renderWithProviders(<DocsPage />);
    expect(await screen.findByText(/укажите response_id/i)).toBeInTheDocument();
  });
});
