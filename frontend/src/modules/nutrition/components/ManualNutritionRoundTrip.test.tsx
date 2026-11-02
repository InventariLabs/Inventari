import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import FoodAndHealthExtra from "@/modules/nutrition/components/FoodAndHealthExtra";
import ProductNutritionOnItemSlot from "@/modules/nutrition/components/ProductNutritionOnItemSlot";
import * as modulesCtx from "@/contexts/ModulesContext";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import type { Item } from "@/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/**
 * A value typed in by hand is saved to the product, not to the record. The
 * edit sheet read the record alone, so reopening it after a save said "No
 * data for this product yet", and the product page showed no nutrition at
 * all. Here the save goes out, the product comes back carrying what was
 * sent — what the refetch after a save returns — and both surfaces must
 * show it.
 */
describe("a nutrition value typed in by hand", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(modulesCtx, "useModules").mockReturnValue({
      enabledModules: ["nutrition"],
      isModuleEnabled: (name: string) => name === "nutrition",
      isLoading: false,
      refreshModules: vi.fn(),
      focusModule: null,
      hiddenModules: [],
    });
  });

  const blank = {
    id: "item-cucumber",
    name: "Cucumber",
    template_id: "tpl-cucumber",
    metadata: {},
    template: { id: "tpl-cucumber", name: "Cucumber", meta_data: {} },
  } as unknown as Item;

  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { mutations: { retry: false } } })
      }
    >
      {children}
    </QueryClientProvider>
  );

  it("is shown again in the edit sheet and on the product page", async () => {
    const save = vi
      .spyOn(productTemplatesApi, "updateNutrition")
      .mockResolvedValue({} as never);

    const sheet = render(
      <FoodAndHealthExtra
        data={{ item: blank, storageType: { type_code: "FRIDGE" } }}
      />,
      { wrapper },
    );
    expect(
      screen.getByText(/no data for this product yet/i),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /enter values by hand/i }),
    );
    fireEvent.change(screen.getByLabelText("energy (kcal)"), {
      target: { value: "15" },
    });
    fireEvent.change(screen.getByLabelText("proteins (g)"), {
      target: { value: "0.7" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const [templateId, sent] = save.mock.calls[0];
    expect(templateId).toBe("tpl-cucumber");
    expect(sent).toEqual({ calories_kcal: 15, protein_g: 0.7 });

    const saved = {
      ...blank,
      template: { ...blank.template, meta_data: { nutrition: sent } },
    } as Item;

    sheet.rerender(
      <FoodAndHealthExtra
        data={{ item: saved, storageType: { type_code: "FRIDGE" } }}
      />,
    );
    expect(
      screen.queryByText(/no data for this product yet/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("0.7")).toBeInTheDocument();

    // Reopening the form starts from what was saved, not from blanks.
    fireEvent.click(
      screen.getByRole("button", { name: /enter values by hand/i }),
    );
    expect(screen.getByLabelText("energy (kcal)")).toHaveValue(15);
    sheet.unmount();

    render(<ProductNutritionOnItemSlot data={{ item: saved }} />);
    expect(
      screen.getByRole("heading", { name: /nutrition per 100 g/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("0.7")).toBeInTheDocument();
  });

  it("leaves the product page without a nutrition card when nothing is known", () => {
    const { container } = render(
      <ProductNutritionOnItemSlot data={{ item: blank }} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("reads a record's own enrichment when the product carries no figures", () => {
    const enriched = {
      ...blank,
      metadata: { nutrition: { energy_kcal: 12, salt: 0.1 } },
    } as unknown as Item;
    render(<ProductNutritionOnItemSlot data={{ item: enriched }} />);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("0.1")).toBeInTheDocument();
  });

  it("opens the form on the figure that was stored, not its float noise", () => {
    // Seeded figures went through a 32-bit float: 0.7 came back as
    // 0.699999988079071 in the field a person was about to correct.
    const stored = {
      ...blank,
      template: {
        ...blank.template,
        meta_data: {
          nutrition: { calories_kcal: 16, protein_g: 0.699999988079071 },
        },
      },
    } as unknown as Item;
    render(
      <FoodAndHealthExtra
        data={{ item: stored, storageType: { type_code: "FRIDGE" } }}
      />,
      { wrapper },
    );
    fireEvent.click(
      screen.getByRole("button", { name: /enter values by hand/i }),
    );
    expect(screen.getByLabelText("proteins (g)")).toHaveValue(0.7);
  });
});
