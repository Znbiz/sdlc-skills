import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../../test/render";
import { ProjectTitle } from "./project-title";

const { updateProductNameMock } = vi.hoisted(() => ({
  updateProductNameMock: vi.fn(),
}));

vi.mock("../../shared/api/endpoints", () => ({
  conversationsApi: {
    updateProductName: updateProductNameMock,
  },
}));

describe("ProjectTitle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("показывает название проекта, а если оно не задано - короткий id", () => {
    renderWithProviders(<ProjectTitle conversationId="conv-12345678" productName={null} />);
    expect(screen.getByRole("heading", { name: "conv-123" })).toBeInTheDocument();
  });

  it("по клику превращает заголовок в поле ввода и сохраняет по blur", async () => {
    updateProductNameMock.mockResolvedValue({});
    const user = userEvent.setup();
    renderWithProviders(<ProjectTitle conversationId="conv-1" productName="Old Name" />);

    await user.click(screen.getByRole("button", { name: /Old Name/ }));
    const input = screen.getByPlaceholderText("Название проекта");
    expect(input).toHaveValue("Old Name");

    await user.clear(input);
    await user.type(input, "New Name");
    await user.tab();

    await waitFor(() => expect(updateProductNameMock).toHaveBeenCalledWith("conv-1", "New Name"));
  });

  it("не отправляет запрос, если значение не изменилось", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProjectTitle conversationId="conv-1" productName="Same Name" />);

    await user.click(screen.getByRole("button", { name: /Same Name/ }));
    await user.tab();

    expect(updateProductNameMock).not.toHaveBeenCalled();
  });

  it("Escape отменяет редактирование без сохранения", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ProjectTitle conversationId="conv-1" productName="Old Name" />);

    await user.click(screen.getByRole("button", { name: /Old Name/ }));
    const input = screen.getByPlaceholderText("Название проекта");
    await user.clear(input);
    await user.type(input, "Draft that should not save");
    await user.keyboard("{Escape}");

    expect(screen.getByRole("heading", { name: "Old Name" })).toBeInTheDocument();
    expect(updateProductNameMock).not.toHaveBeenCalled();
  });
});
