import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TokenUsage } from "../../shared/api/models";
import { TokenUsageStatsCard, mergeTokenUsage, restTokenUsageToView } from "./workflow-run-panel";

describe("restTokenUsageToView", () => {
  it("конвертирует snake_case usage из REST-ответа в camelCase view-модель", () => {
    const usage: Record<string, TokenUsage> = {
      "claude-sonnet-4-5": { input_tokens: 100, output_tokens: 20 },
    };
    expect(restTokenUsageToView(usage)).toEqual({
      "claude-sonnet-4-5": { inputTokens: 100, outputTokens: 20 },
    });
  });

  it("возвращает пустой объект для пустого usage", () => {
    expect(restTokenUsageToView({})).toEqual({});
  });
});

describe("mergeTokenUsage", () => {
  it("берёт REST-снепшот, если SSE-стрим ещё ничего не прислал", () => {
    const rest = { "claude-sonnet-4-5": { inputTokens: 100, outputTokens: 20 } };
    expect(mergeTokenUsage(rest, {})).toEqual(rest);
  });

  it("подхватывает более свежие данные из REST-опроса, даже если SSE-стрим отстал", () => {
    // Регрессия: раньше компонент один раз получал что-то из SSE и после этого навсегда
    // игнорировал более новый REST-снепшот, даже если стрим отстал из-за пропущенного
    // при реконнекте события (живой bus не реплеит историю).
    const staleFromStream = { "claude-sonnet-4-5": { inputTokens: 100, outputTokens: 20 } };
    const freshFromRest = { "claude-sonnet-4-5": { inputTokens: 250, outputTokens: 40 } };
    expect(mergeTokenUsage(freshFromRest, staleFromStream)).toEqual(freshFromRest);
  });

  it("объединяет разные модели из обоих источников", () => {
    const rest = { "claude-sonnet-4-5": { inputTokens: 100, outputTokens: 20 } };
    const stream = { "gpt-4o-mini": { inputTokens: 50, outputTokens: 10 } };
    expect(mergeTokenUsage(rest, stream)).toEqual({
      "claude-sonnet-4-5": { inputTokens: 100, outputTokens: 20 },
      "gpt-4o-mini": { inputTokens: 50, outputTokens: 10 },
    });
  });
});

describe("TokenUsageStatsCard", () => {
  it("показывает заглушку, если данных о токенах ещё нет", () => {
    render(<TokenUsageStatsCard tokenUsageByModel={{}} />);
    expect(screen.getByText("Данных о расходе токенов пока нет.")).toBeInTheDocument();
  });

  it("показывает строку с инпут/аутпут токенами для одной модели", () => {
    render(
      <TokenUsageStatsCard
        tokenUsageByModel={{ "claude-sonnet-4-5": { inputTokens: 1234, outputTokens: 56 } }}
      />,
    );
    expect(screen.getByText("claude-sonnet-4-5")).toBeInTheDocument();
    // ru-RU форматирует разделитель тысяч разными видами пробела в зависимости от ICU-версии
    // Node - сравниваем без пробелов, чтобы тест не зависел от конкретного символа.
    expect(screen.getByText((content) => content.replace(/\s/g, "") === "1234")).toBeInTheDocument();
    expect(screen.getByText("56")).toBeInTheDocument();
  });

  it("показывает отдельные строки для каждой модели при переключении модели", () => {
    render(
      <TokenUsageStatsCard
        tokenUsageByModel={{
          "claude-sonnet-4-5": { inputTokens: 100, outputTokens: 20 },
          "gpt-4o-mini": { inputTokens: 50, outputTokens: 10 },
        }}
      />,
    );
    expect(screen.getByText("claude-sonnet-4-5")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
  });
});
