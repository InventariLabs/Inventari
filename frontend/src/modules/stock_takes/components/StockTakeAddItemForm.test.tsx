import { describe, expect, it, vi } from "vitest";
import { fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import StockTakeAddItemForm from "./StockTakeAddItemForm";
import { onePage } from "@/test/mocks/page";

/**
 * The category picker in the stock-take surplus form is an *offer*: the
 * module-data policy has to govern it the way it governs the category filter
 * on the products list. The operator adding a missing position could pick a
 * category whose records the same screens then never show.
 */

const CORE = {
  id: "cat-1",
  code: "dairy",
  name: "Dairy",
  context_tag: null,
};
const MODULE = {
  id: "cat-eq",
  code: "LAPTOP",
  name: "Laptop",
  context_tag: "equipment",
};

const noop = () => {};

function renderForm() {
  return render(
    <StockTakeAddItemForm
      name=""
      barcode=""
      quantity={1}
      categoryId=""
      uomId=""
      isPending={false}
      error={null}
      onNameChange={noop}
      onBarcodeChange={noop}
      onQuantityChange={noop}
      onCategoryIdChange={noop}
      onUomIdChange={noop}
      onSubmit={noop}
    />,
  );
}

function serveCategories() {
  server.use(
    http.get("/api/v1/categories", ({ request }) => {
      const url = new URL(request.url);
      const exclude =
        url.searchParams.get("exclude_module_contexts") === "true";
      return HttpResponse.json(onePage(exclude ? [CORE] : [CORE, MODULE]));
    }),
  );
}

describe("StockTakeAddItemForm category picker", () => {
  it("does not offer a module-owned category while module data is off", async () => {
    serveCategories();
    renderForm();

    expect(
      await screen.findByRole("option", { name: "Dairy" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Laptop" }),
    ).not.toBeInTheDocument();
  });

  it("offers every category once the organization mixes module data", async () => {
    server.use(
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Organization",
          currency: "PLN",
          settings: { show_module_data: true },
        }),
      ),
    );
    serveCategories();
    renderForm();

    expect(
      await screen.findByRole("option", { name: "Laptop" }),
    ).toBeInTheDocument();
  });
});

describe("StockTakeAddItemForm add button", () => {
  it("keeps the shared primary fill instead of a lighter override", () => {
    renderForm();

    const add = screen.getByRole("button", { name: /add/i });
    expect(add).toHaveClass("bg-primary-700");
    expect(add).not.toHaveClass("bg-primary-600");
  });
});

/**
 * The form is controlled by the counting screen; each field has to report
 * its own value to its own handler. A quantity cleared to nothing must come
 * back as one — never NaN, which the save would send as null — and the Add
 * button must stay shut until there is a name.
 */
describe("StockTakeAddItemForm — each field reports to its own handler", () => {
  function renderWithSpies(overrides: { name?: string; error?: unknown } = {}) {
    const handlers = {
      onNameChange: vi.fn(),
      onBarcodeChange: vi.fn(),
      onQuantityChange: vi.fn(),
      onCategoryIdChange: vi.fn(),
      onUomIdChange: vi.fn(),
      onSubmit: vi.fn(),
    };
    render(
      <StockTakeAddItemForm
        name={overrides.name ?? ""}
        barcode=""
        quantity={1}
        categoryId=""
        uomId=""
        isPending={false}
        error={overrides.error ?? null}
        {...handlers}
      />,
    );
    return handlers;
  }

  it("passes name, barcode, quantity, category and unit through", async () => {
    serveCategories();
    server.use(
      http.get("/api/v1/uoms", () =>
        HttpResponse.json(
          onePage([{ id: "uom-kg", name: "Kilogram", symbol: "kg" }]),
        ),
      ),
    );
    const handlers = renderWithSpies();
    await screen.findByRole("option", { name: "Dairy" });
    await screen.findByRole("option", { name: /kg|Kilogram/ });

    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Oat milk" },
    });
    fireEvent.change(screen.getByLabelText("Barcode"), {
      target: { value: "5901234" },
    });
    fireEvent.change(screen.getByLabelText("Quantity"), {
      target: { value: "4" },
    });
    fireEvent.change(screen.getByLabelText("Category"), {
      target: { value: "cat-1" },
    });
    fireEvent.change(screen.getByLabelText("Unit"), {
      target: { value: "uom-kg" },
    });

    expect(handlers.onNameChange).toHaveBeenCalledWith("Oat milk");
    expect(handlers.onBarcodeChange).toHaveBeenCalledWith("5901234");
    expect(handlers.onQuantityChange).toHaveBeenCalledWith(4);
    expect(handlers.onCategoryIdChange).toHaveBeenCalledWith("cat-1");
    expect(handlers.onUomIdChange).toHaveBeenCalledWith("uom-kg");
  });

  it("turns a cleared quantity into one", () => {
    const handlers = renderWithSpies();
    fireEvent.change(screen.getByLabelText("Quantity"), {
      target: { value: "" },
    });
    expect(handlers.onQuantityChange).toHaveBeenCalledWith(1);
  });

  it("keeps Add shut while the name is empty", () => {
    const blank = renderWithSpies();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    expect(blank.onSubmit).not.toHaveBeenCalled();
  });

  it("submits a named item and says why a previous add was refused", () => {
    const handlers = renderWithSpies({
      name: "Oat milk",
      error: new Error("boom"),
    });
    expect(screen.getByText("Failed to add item")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(handlers.onSubmit).toHaveBeenCalledTimes(1);
  });
});
