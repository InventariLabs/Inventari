import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { render } from "@/test/utils";
import type { CategoryDTO } from "@/types";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import BulkEditModal from "./BulkEditModal";

type MutateOptions = {
  onSuccess?: (data: unknown) => void;
  onError?: (error: unknown) => void;
};

const mocks = vi.hoisted(() => ({ mutate: vi.fn() }));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), dismiss: vi.fn() },
}));

vi.mock("@/modules/inventory/hooks/useItemMutations", () => ({
  useBulkUpdateItems: () => ({ mutate: mocks.mutate, isPending: false }),
}));

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "PLN",
}));

vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => true,
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useScopedCategories: vi.fn(),
}));

// The location picker searches the server; here it is the value it hands back.
vi.mock("@/module-sdk", async () => {
  const actual =
    await vi.importActual<typeof import("@/module-sdk")>("@/module-sdk");
  return {
    ...actual,
    LocationCombobox: ({
      onChange,
      "aria-label": label,
    }: {
      onChange: (id: string) => void;
      "aria-label": string;
    }) => (
      <button
        type="button"
        aria-label={label}
        onClick={() => onChange("loc-9")}
      >
        pick location
      </button>
    ),
  };
});

const pantry = {
  id: "cat-pantry",
  name: "Pantry",
  is_module_owned: false,
} as unknown as CategoryDTO;
const laptops = {
  id: "cat-laptops",
  name: "Laptops",
  is_module_owned: true,
  module_name: "equipment",
} as unknown as CategoryDTO;

function lastPayload() {
  return mocks.mutate.mock.calls.at(-1)?.[0] as {
    item_ids: string[];
    update_data: Record<string, unknown>;
  };
}

function lastOptions(): MutateOptions {
  return mocks.mutate.mock.calls.at(-1)?.[1] as MutateOptions;
}

/**
 * The bulk edit writes only the fields whose box is ticked, into every
 * selected record. A payload that carries an unticked field overwrites it
 * across the whole selection; a price typed with a comma that arrives as
 * text (or NaN) is refused or stored wrong; an apply with nothing ticked
 * that still sends a request writes nothing and says it did.
 */
describe("BulkEditModal — what the apply sends", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useScopedCategories).mockReturnValue({
      all: [pantry, laptops],
      scoped: [pantry, laptops],
    } as unknown as ReturnType<typeof useScopedCategories>);
  });

  function open() {
    const onClose = vi.fn();
    const onSuccess = vi.fn();
    render(
      <BulkEditModal
        itemIds={["a", "b"]}
        onClose={onClose}
        onSuccess={onSuccess}
      />,
    );
    return { onClose, onSuccess };
  }

  it("offers no apply until a field is ticked", async () => {
    const user = userEvent.setup();
    open();

    // Pressable with nothing ticked, the button answered the press with a
    // toast saying what the subtitle above it already asks for.
    const apply = screen.getByRole("button", { name: "Apply changes" });
    expect(apply).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /Brand/ }));
    expect(apply).toBeEnabled();
    await user.click(screen.getByRole("checkbox", { name: /Brand/ }));
    expect(apply).toBeDisabled();
    expect(mocks.mutate).not.toHaveBeenCalled();
  });

  it("sends exactly the ticked fields, the price as a number read with either mark", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("checkbox", { name: /Location/ }));
    await user.click(screen.getByRole("button", { name: "Location" }));
    await user.click(screen.getByRole("checkbox", { name: /Category/ }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Category" }),
      "cat-pantry",
    );
    await user.click(screen.getByRole("checkbox", { name: /Price \(PLN\)/ }));
    await user.type(screen.getByRole("textbox", { name: "Price" }), "12,50");
    await user.click(screen.getByRole("checkbox", { name: /Brand/ }));
    await user.type(screen.getByRole("textbox", { name: "Brand" }), "Acme");
    // Ticked and left empty: a ticked field with no value is not a write.
    await user.click(screen.getByRole("checkbox", { name: /Expiry Date/ }));

    await user.click(screen.getByRole("button", { name: "Apply changes" }));

    expect(lastPayload()).toEqual({
      item_ids: ["a", "b"],
      update_data: {
        location_id: "loc-9",
        category_id: "cat-pantry",
        purchase_price: 12.5,
        brand: "Acme",
        unit_confirmed_over_template: false,
      },
    });
  });

  it("drops a price that is not a number, and a field ticked off again", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("checkbox", { name: /Price \(PLN\)/ }));
    await user.type(screen.getByRole("textbox", { name: "Price" }), "abc");
    await user.click(screen.getByRole("checkbox", { name: /Brand/ }));
    await user.type(screen.getByRole("textbox", { name: "Brand" }), "Acme");
    await user.click(screen.getByRole("checkbox", { name: /Brand/ }));

    await user.click(screen.getByRole("button", { name: "Apply changes" }));

    expect(mocks.mutate).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("sets an expiry date from a preset", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("checkbox", { name: /Expiry Date/ }));
    await user.click(screen.getByRole("combobox", { name: "Expiry Date" }));
    await user.click(screen.getByRole("button", { name: "In a week" }));
    await user.click(screen.getByRole("button", { name: "Apply changes" }));

    expect(lastPayload().update_data.expiry_date).toMatch(
      /^\d{4}-\d{2}-\d{2}$/,
    );
  });

  it("warns that a module's category moves the records into that module", async () => {
    const user = userEvent.setup();
    open();

    await user.click(screen.getByRole("checkbox", { name: /Category/ }));
    expect(screen.queryByTestId("category-module-warning")).toBeNull();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Category" }),
      "cat-laptops",
    );

    expect(screen.getByTestId("category-module-warning")).toHaveTextContent(
      "Laptops",
    );
  });

  it("reports the count the server updated and hands back, or the refusal", async () => {
    const user = userEvent.setup();
    const { onSuccess } = open();

    await user.click(screen.getByRole("checkbox", { name: /Brand/ }));
    await user.type(screen.getByRole("textbox", { name: "Brand" }), "Acme");
    await user.click(screen.getByRole("button", { name: "Apply changes" }));

    lastOptions().onSuccess?.({ updated: 2 });
    expect(toast.success).toHaveBeenCalledWith("Updated 2 products");
    expect(onSuccess).toHaveBeenCalled();

    lastOptions().onError?.(new Error("x"));
    expect(toast.error).toHaveBeenCalledWith(
      "Could not change the selected products",
    );
  });

  it("closes from the cancel button", async () => {
    const user = userEvent.setup();
    const { onClose } = open();
    const sheet = screen.getByRole("dialog");

    await user.click(within(sheet).getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
