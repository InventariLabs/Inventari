import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { WhereUsedSlot } from "./WhereUsedSlot";
import { withLanguage } from "@/test/mocks/i18n";
import type { Item } from "@/types";

const mocks = vi.hoisted(() => ({
  useWhereUsed: vi.fn(),
}));

vi.mock("@/modules/maker/hooks/useBom", () => ({
  useWhereUsed: mocks.useWhereUsed,
}));

const item = { template_id: "tpl-flour" } as unknown as Item;

function renderSlot(data?: {
  item?: Item;
  requestLeave?: (go: () => void) => void;
}) {
  return render(
    <MemoryRouter>
      <WhereUsedSlot data={data ?? { item }} />
    </MemoryRouter>,
  );
}

describe("WhereUsedSlot", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing without a template id", () => {
    mocks.useWhereUsed.mockReturnValue({ data: undefined, isLoading: false });
    renderSlot({ item: undefined });
    expect(screen.queryByTestId("maker-where-used")).toBeNull();
  });

  it("steps aside when the template is used nowhere", () => {
    // Most products in most organizations are in no BOM at all; a heading and
    // a line saying so, in every product form, is not worth its space.
    mocks.useWhereUsed.mockReturnValue({
      data: { items: [] },
      isLoading: false,
    });
    renderSlot();
    expect(screen.queryByTestId("maker-where-used")).toBeNull();
  });

  it("says the answer is missing, with a retry, when the read failed", () => {
    // Nothing rendered means "used nowhere"; a failed read must not pass for it.
    const refetch = vi.fn();
    mocks.useWhereUsed.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    });
    renderSlot();
    expect(screen.getByTestId("maker-where-used")).toBeTruthy();
    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("lists consuming BOMs with per-batch quantity", () => {
    mocks.useWhereUsed.mockReturnValue({
      data: {
        items: [
          {
            recipe_id: "recipe-1",
            recipe_name: "Bread",
            output_template_id: "tpl-bread",
            output_template_name: "Bread",
            qty_per_batch: "0.5000",
            unit: "kg",
          },
        ],
      },
      isLoading: false,
    });
    renderSlot();
    expect(screen.getByTestId("maker-where-used-link").textContent).toBe(
      "Bread",
    );
    // The unit travels inside the formatted quantity, translated like
    // everywhere else in the module — "0.5 kg", not the wire's "0.5000 kg".
    expect(screen.getByText(/0\.5 kg per batch/)).toBeTruthy();
    expect(screen.queryByText(/0\.5000/)).toBeNull();
  });

  it("writes the per-batch unit in the reader's language", async () => {
    // The line used to paste the raw symbol, so a Polish interface said
    // "2 pcs na partię" beside lists saying "2 szt.".
    mocks.useWhereUsed.mockReturnValue({
      data: {
        items: [
          {
            recipe_id: "recipe-1",
            recipe_name: "Bread",
            output_template_id: "tpl-bread",
            output_template_name: "Bread",
            qty_per_batch: "2.5000",
            unit: "pcs",
          },
        ],
      },
      isLoading: false,
    });
    await withLanguage("pl", () => {
      renderSlot();
      expect(screen.getByText(/2,5 szt\. na partię/)).toBeTruthy();
      expect(screen.queryByText(/2,?5\s+pcs/)).toBeNull();
    });
  });

  it("asks the host form before navigating out of it", () => {
    mocks.useWhereUsed.mockReturnValue({
      data: {
        items: [
          {
            recipe_id: "recipe-1",
            recipe_name: "Bread",
            output_template_id: "tpl-bread",
            output_template_name: "Bread",
            qty_per_batch: "0.5000",
            unit: "kg",
          },
        ],
      },
      isLoading: false,
    });
    const requestLeave = vi.fn();
    renderSlot({ item, requestLeave });

    fireEvent.click(screen.getByTestId("maker-where-used-link"));
    expect(requestLeave).toHaveBeenCalledWith(expect.any(Function));
  });
});
