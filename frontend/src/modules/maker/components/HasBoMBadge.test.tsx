import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { HasBoMBadge } from "./HasBoMBadge";

let summaryData: {
  items: {
    template_id: string;
    line_count: number;
    default_recipe_id: string | null;
  }[];
} = { items: [] };

vi.mock("@/modules/maker/hooks/useBom", () => ({
  useBomSummary: () => ({ data: summaryData }),
}));

function renderBadge(templateId: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <HasBoMBadge templateId={templateId} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HasBoMBadge", () => {
  it("renders the badge when the template has a BoM", () => {
    summaryData = {
      items: [{ template_id: "tpl-1", line_count: 3, default_recipe_id: null }],
    };
    renderBadge("tpl-1");
    expect(screen.getByTestId("maker-has-bom-badge")).toBeInTheDocument();
  });

  it("links to the default recipe card when one exists", () => {
    summaryData = {
      items: [
        {
          template_id: "tpl-1",
          line_count: 3,
          default_recipe_id: "recipe-1",
        },
      ],
    };
    renderBadge("tpl-1");
    const link = screen.getByTestId("maker-has-bom-badge");
    expect(link).toHaveAttribute("href", "/maker/recipes/recipe-1");
  });

  it("falls back to the catalog when there is no default recipe to open", () => {
    summaryData = {
      items: [{ template_id: "tpl-1", line_count: 3, default_recipe_id: null }],
    };
    renderBadge("tpl-1");
    const link = screen.getByTestId("maker-has-bom-badge");
    expect(link).toHaveAttribute("href", "/maker");
  });

  it("announces an action and prints no word that could name the row", () => {
    summaryData = {
      items: [{ template_id: "tpl-1", line_count: 3, default_recipe_id: null }],
    };
    renderBadge("tpl-1");
    const link = screen.getByTestId("maker-has-bom-badge");
    // A bare noun here read as "this row is a formula" — the jam a closed
    // production order put on the shelf looked like a recipe in the stock list.
    expect(link.textContent?.trim()).toBe("");
    expect(link).toHaveAccessibleName();
  });

  it("renders nothing when the template has no BoM", () => {
    summaryData = {
      items: [{ template_id: "tpl-2", line_count: 1, default_recipe_id: null }],
    };
    const { container } = renderBadge("tpl-1");
    expect(container).toBeEmptyDOMElement();
  });
});
