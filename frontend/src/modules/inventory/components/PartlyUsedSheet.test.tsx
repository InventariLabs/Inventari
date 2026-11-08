import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { addWeeks, format } from "date-fns";
import { describe, it, expect, vi } from "vitest";

import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import type { LabelScanView } from "@/types";
import PartlyUsedSheet from "./PartlyUsedSheet";
import StockActionSheet from "./StockActionSheet";
import { onePage } from "@/test/mocks/page";

/**
 * "Use partially" asks how much is LEFT, in the unit on the bag, and
 * a card that cannot say what a piece holds is only ever opened or finished.
 */

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const twoKilos = { value: 2, symbol: "kg", uomId: "uom-kg" };

describe("PartlyUsedSheet — a card that records what a piece holds", () => {
  it("offers shares of the piece, each shown in the unit on the bag", async () => {
    render(
      <PartlyUsedSheet
        itemName="Flour"
        measure={twoKilos}
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: /3\/4 · 1\.5 kg/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /1\/2 · 1 kg/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /1\/4 · 0\.5 kg/ }),
    ).toBeInTheDocument();
  });

  it("sends what is left, in the measure's unit, when a share is chosen", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <PartlyUsedSheet
        itemName="Flour"
        measure={twoKilos}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByRole("button", { name: /3\/4/ }));

    expect(onSubmit).toHaveBeenCalledWith({ left: 1.5, leftUomId: "uom-kg" });
    expect(onClose).toHaveBeenCalled();
  });

  it("says a refusal out loud and stays open with the choice", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockRejectedValue(new Error("refused"));
    const onClose = vi.fn();
    render(
      <PartlyUsedSheet
        itemName="Flour"
        measure={twoKilos}
        onSubmit={onSubmit}
        onClose={onClose}
      />,
    );

    await user.click(screen.getByRole("button", { name: /3\/4/ }));

    expect(toast.error).toHaveBeenCalledWith(
      "The action could not be completed.",
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /3\/4/ })).toBeEnabled();
  });

  it("says empty as zero left", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <PartlyUsedSheet
        itemName="Flour"
        measure={twoKilos}
        onSubmit={onSubmit}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Empty" }));

    expect(onSubmit).toHaveBeenCalledWith({ left: 0 });
  });

  it("takes a typed amount and refuses one above the whole piece", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <PartlyUsedSheet
        itemName="Flour"
        measure={twoKilos}
        onSubmit={onSubmit}
        onClose={vi.fn()}
      />,
    );
    const field = screen.getByLabelText("Left (kg)");
    const save = screen.getByRole("button", { name: "Save" });

    await user.type(field, "2.5");
    expect(save).toBeDisabled();

    await user.clear(field);
    await user.type(field, "1.2");
    await user.click(save);

    expect(onSubmit).toHaveBeenCalledWith({ left: 1.2, leftUomId: "uom-kg" });
  });

  it("asks in Polish", async () => {
    await withLanguage("pl", () => {
      render(
        <PartlyUsedSheet
          itemName="Mąka"
          measure={twoKilos}
          onSubmit={vi.fn()}
          onClose={vi.fn()}
        />,
      );
      expect(screen.getByText("Ile zostało?")).toBeInTheDocument();
    });
  });
});

describe("PartlyUsedSheet — a card that does not say what a piece holds", () => {
  it("explains the limitation for packs with a recorded weight", () => {
    render(
      <PartlyUsedSheet
        itemName="Eggs"
        measure={null}
        packCounted
        onSubmit={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.getByText(/packs cannot be measured as fractions/i),
    ).toBeInTheDocument();
  });
  it("only opens or finishes, and never invents a fraction", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <PartlyUsedSheet
        itemName="Eggs"
        measure={null}
        onSubmit={onSubmit}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: /3\/4/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Mark as opened" }));
    expect(onSubmit).toHaveBeenLastCalledWith({});

    await user.click(screen.getByRole("button", { name: "Finished" }));
    expect(onSubmit).toHaveBeenLastCalledWith({ left: 0 });
  });
});

describe("StockActionSheet — use partially", () => {
  const scan = (unitCategoryId: string): LabelScanView =>
    ({
      status: "product_stock",
      label_code: "STM-0001",
      message_key: "scan:result.product",
      message_params: { product: "Flour" },
      action: "show_stock_actions",
      stock_summary: {
        total_quantity: 3,
        unit: "pcs",
        template: {
          name: "Flour",
          uom_id: unitCategoryId,
          weight_value: 2,
          weight_uom_id: "uom-kg",
        },
        items: [
          { id: "item-1", expiry_date: null, location: "Pantry", quantity: 3 },
        ],
      },
    }) as LabelScanView;

  const catalogue = () =>
    server.use(
      http.get("*/uoms/categories", () =>
        HttpResponse.json(
          onePage([
            {
              id: "cat-weight",
              name: "Weight",
              uoms: [
                {
                  id: "uom-kg",
                  category_id: "cat-weight",
                  name: "Kilogram",
                  symbol: "kg",
                },
                {
                  id: "uom-g",
                  category_id: "cat-weight",
                  name: "Gram",
                  symbol: "g",
                },
              ],
            },
            {
              id: "cat-unit",
              name: "Unit",
              uoms: [
                {
                  id: "uom-pcs",
                  category_id: "cat-unit",
                  name: "Piece",
                  symbol: "pcs",
                },
              ],
            },
          ]),
        ),
      ),
    );

  it("asks about the record the button belongs to", async () => {
    catalogue();
    const user = userEvent.setup();
    const onUsePartially = vi.fn().mockResolvedValue(undefined);
    render(
      <StockActionSheet
        data={scan("uom-pcs")}
        onClose={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
        onUsePartially={onUsePartially}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: "Use partially" }),
    );
    // The sheet is named after the product, not the shelf it stands on.
    expect(screen.queryByRole("dialog", { name: "Pantry" })).toBeNull();
    await user.click(screen.getByRole("button", { name: /1\/2 · 1 kg/ }));

    expect(onUsePartially).toHaveBeenCalledWith("item-1", {
      left: 1,
      leftUomId: "uom-kg",
    });
  });

  it("offers nothing on a card kept in a measured unit", async () => {
    catalogue();
    render(
      <StockActionSheet
        data={scan("uom-kg")}
        onClose={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
        onUsePartially={vi.fn()}
      />,
    );

    await screen.findByText("Pantry");
    expect(screen.queryByRole("button", { name: "Use partially" })).toBeNull();
  });

  it("offers nothing to someone who cannot write", async () => {
    catalogue();
    render(
      <StockActionSheet
        data={scan("uom-pcs")}
        canWrite={false}
        onClose={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
        onUsePartially={vi.fn()}
      />,
    );

    await screen.findByText("Pantry");
    expect(screen.queryByRole("button", { name: "Use partially" })).toBeNull();
  });
});

describe("PartlyUsedSheet — an optional use-by date", () => {
  it("sends nothing about a date when none is given", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <PartlyUsedSheet
        itemName="Flour"
        measure={twoKilos}
        onSubmit={onSubmit}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /1\/2/ }));

    expect(onSubmit).toHaveBeenCalledWith({ left: 1, leftUomId: "uom-kg" });
  });

  it("sends the date with whatever is chosen, including a bare opening", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <PartlyUsedSheet
        itemName="Flour"
        measure={null}
        onSubmit={onSubmit}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText(/use by after opening/i));
    await user.click(screen.getAllByTestId("date-preset")[0]);
    await user.click(screen.getByRole("button", { name: /mark as opened/i }));

    expect(onSubmit).toHaveBeenCalledWith({
      useBy: format(addWeeks(new Date(), 1), "yyyy-MM-dd"),
    });
  });
});
