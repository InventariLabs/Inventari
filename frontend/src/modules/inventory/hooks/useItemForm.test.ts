import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { toast } from "sonner";
import { QueryWrapper } from "@/test/queryWrapper";
import { useFormMemoryStore } from "@/store/formMemoryStore";
import { useUoms } from "@/modules/shared/hooks/useUoms";
import { focusFirstInvalidField } from "../utils/focusFirstInvalidField";
import { useItemForm, type ItemFormData } from "./useItemForm";

// react-i18next and formMemoryStore are already mocked globally in src/test/setup.ts.
// formMemoryStore needs to be reset between tests via its own setState method.

// UoM ids as served by the MSW handler for /api/v1/uoms/categories:
// "1" gram (Weight), "2" kilogram (Weight), "3" piece (Count).
const GRAM = "1";
const KILOGRAM = "2";
const PIECE = "3";

const defaultProps = {
  onSubmit: vi.fn(),
};

vi.mock("sonner", () => ({
  toast: { info: vi.fn(), success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

vi.mock("../utils/focusFirstInvalidField", () => ({
  focusFirstInvalidField: vi.fn(),
}));

// The form reads the stats module's "Show inventory value" switch: where it
// is off, the purchase-price field goes. Mutable handle; on is the default,
// as it is for an organization without the stats module.
const inventoryValue = { shown: true };
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => inventoryValue.shown,
}));

beforeEach(() => {
  vi.mocked(toast.info).mockClear();
  vi.mocked(toast.warning).mockClear();
  inventoryValue.shown = true;
});

/** The hook reads the UoM catalogue, so it needs a query client. */
function renderItemForm(props: Parameters<typeof useItemForm>[0]) {
  return renderHook(() => useItemForm(props), { wrapper: QueryWrapper });
}

/** Waits until the UoM catalogue has arrived, i.e. until the hook can tell a
 * continuous unit from a discrete one. */
async function waitForUomCategory(
  result: { current: { uomCategoryName: string | null } },
  expected: string,
) {
  await waitFor(() => expect(result.current.uomCategoryName).toBe(expected));
}

/** An Item as it comes back from the API: a total weight in kg, a uom_id,
 * and no unit symbol anywhere. */
function apiItem(fields: Record<string, unknown>): Partial<ItemFormData> {
  return fields as unknown as Partial<ItemFormData>;
}

describe("useItemForm — initial state", () => {
  it("initializes with empty default form data", () => {
    const { result } = renderItemForm(defaultProps);

    expect(result.current.formData.name).toBe("");
    expect(result.current.formData.quantity).toBe("1");
    expect(result.current.errors).toEqual({});
  });

  it("initializes with provided initialData", () => {
    const { result } = renderItemForm({
      ...defaultProps,
      initialData: { name: "Test Item", barcode: "12345" },
    });

    expect(result.current.formData.name).toBe("Test Item");
    expect(result.current.formData.barcode).toBe("12345");
  });

  it("shows the product's code on a record that carries none itself", async () => {
    // A scan reads the code off the product, and that is where the record's
    // own save puts it — so the record's column is empty for every product
    // that has a code. The field shows the code the scanner answers to.
    const { result } = renderItemForm({
      ...defaultProps,
      initialData: apiItem({
        name: "Patch cable",
        barcode: null,
        template: { barcode: "5901234123457" },
      }),
    });

    await waitFor(() =>
      expect(result.current.formData.barcode).toBe("5901234123457"),
    );
    expect(result.current.isDirty).toBe(false);
  });

  // The unit lives in uom_id only. Nothing seeds a unit symbol any
  // more, so no code may branch on one.
  it("carries no unit symbol in form state", () => {
    const { result } = renderItemForm(defaultProps);

    expect(result.current.formData.unit).toBeUndefined();
  });

  // The form does not pre-fill a unit any more: which unit a record
  // carries is decided once, by the backend — a matched template's unit
  // wins, pieces are the backend's answer for an unknown product. A form
  // that shipped pcs itself overruled the template before the backend
  // saw the request, so a record could contradict its own catalogue row.
  it("starts a new item without claiming a unit", async () => {
    const onSubmit = vi.fn();
    // Read the UoM catalogue through the hook's own query client: the
    // old pre-fill effect only fired once the catalogue had arrived, so a
    // submit before that point could not tell the two versions apart.
    const { result } = renderHook(
      () => ({
        form: useItemForm({ onSubmit }),
        uoms: useUoms(),
      }),
      { wrapper: QueryWrapper },
    );
    await waitFor(() => expect(result.current.uoms.data).toBeDefined());
    // Let the effects that react to the arrived catalogue run.
    await act(async () => {});

    expect(result.current.form.formData.uom_id).toBeUndefined();

    act(() => {
      result.current.form.handleInputChange("name", "Matched product");
      result.current.form.handleInputChange("location_id", "loc-1");
    });
    act(() => {
      result.current.form.submit();
    });

    expect(onSubmit).toHaveBeenCalledOnce();
    // No uom_id in the payload: the backend picks the unit — a matched
    // template's unit wins, pieces are its answer for an unknown product.
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.uom_id).toBeUndefined();

    // The successful create fed the batch-mode memory (last-used
    // storage); clear it so later tests still start from nothing.
    useFormMemoryStore.getState().clear();
  });

  it("does not put a unit on an item that was saved without one", async () => {
    const { result } = renderItemForm({
      ...defaultProps,
      form: "item_edit",
      initialData: { name: "Legacy item", quantity: "2" },
    });

    await waitFor(() =>
      expect(result.current.formData.name).toBe("Legacy item"),
    );
    expect(result.current.formData.uom_id).toBeUndefined();
  });
});

describe("useItemForm — a stored quantity in the edit form", () => {
  it.each([
    ["20.000", "20"],
    ["1.500", "1.5"],
    ["0.000", "0"],
    ["100.000", "100"],
  ])("shows %s as %s, without the column's padding", async (stored, shown) => {
    const { result } = renderItemForm({
      ...defaultProps,
      form: "item_edit",
      initialData: { name: "Hex nut", quantity: stored },
    });

    await waitFor(() => expect(result.current.formData.name).toBe("Hex nut"));
    expect(result.current.formData.quantity).toBe(shown);
  });
});

describe("useItemForm — the record refetched under an edit in progress", () => {
  /** The record as the edit sheet is handed it, re-rendered with a new
   * answer from the server while the form is open. */
  function openOnRecord(first: Record<string, unknown>) {
    return renderHook(
      ({ record }) =>
        useItemForm({
          ...defaultProps,
          form: "item_edit",
          initialData: apiItem(record),
        }),
      { wrapper: QueryWrapper, initialProps: { record: first } },
    );
  }

  it("keeps what the reader typed when the record is refetched", async () => {
    const { result, rerender } = openOnRecord({
      name: "Review bolt",
      quantity: "20.000",
      label_code: "QAR-O5X6",
    });
    await waitFor(() =>
      expect(result.current.formData.name).toBe("Review bolt"),
    );

    act(() => result.current.handleInputChange("name", "Unsaved name"));
    // Freeing the label refetches the product: the label is gone from it.
    rerender({
      record: { name: "Review bolt", quantity: "20.000", label_code: null },
    });

    expect(result.current.formData.name).toBe("Unsaved name");
    expect(result.current.isDirty).toBe(true);
  });

  it("takes the record's new answer for a field nobody touched", async () => {
    const { result, rerender } = openOnRecord({
      name: "Review bolt",
      quantity: "20.000",
      label_code: "QAR-O5X6",
    });
    await waitFor(() =>
      expect(result.current.formData.name).toBe("Review bolt"),
    );

    act(() => result.current.handleInputChange("name", "Unsaved name"));
    rerender({
      record: { name: "Review bolt", quantity: "18.000", label_code: null },
    });

    expect(result.current.formData.quantity).toBe("18");
    expect(result.current.formData.label_code).toBeNull();
    expect(result.current.formData.name).toBe("Unsaved name");
  });

  it("reports a form nobody touched as untouched after a refetch", async () => {
    const { result, rerender } = openOnRecord({
      name: "Review bolt",
      label_code: "QAR-O5X6",
    });
    await waitFor(() =>
      expect(result.current.formData.name).toBe("Review bolt"),
    );

    rerender({ record: { name: "Renamed elsewhere", label_code: null } });

    expect(result.current.formData.name).toBe("Renamed elsewhere");
    expect(result.current.isDirty).toBe(false);
  });
});

describe("useItemForm — handleInputChange", () => {
  it("updates form field", () => {
    const { result } = renderItemForm(defaultProps);

    act(() => {
      result.current.handleInputChange("name", "New Name");
    });

    expect(result.current.formData.name).toBe("New Name");
  });

  it("updates metadata when isMetadata=true", () => {
    const { result } = renderItemForm(defaultProps);

    act(() => {
      result.current.handleInputChange("color", "red", true);
    });

    expect(result.current.formData.metadata.color).toBe("red");
  });

  it("clears field error when field is updated", () => {
    const { result } = renderItemForm(defaultProps);

    // Manually inject an error
    act(() => {
      result.current.setErrors({ name: "Required" });
    });

    expect(result.current.errors.name).toBe("Required");

    // Update the field — error should clear
    act(() => {
      result.current.handleInputChange("name", "Something");
    });

    expect(result.current.errors.name).toBeUndefined();
  });
});

describe("useItemForm — handleMetadataChange", () => {
  it("is an alias for handleInputChange with isMetadata=true", () => {
    const { result } = renderItemForm(defaultProps);

    act(() => {
      result.current.handleMetadataChange("notes", "test note");
    });

    expect(result.current.formData.metadata.notes).toBe("test note");
  });
});

describe("useItemForm — validation on submit", () => {
  it("sets error for empty name on submit", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    act(() => {
      result.current.submit();
    });

    expect(result.current.errors.name).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("sets error for missing location_id on submit", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    act(() => {
      result.current.handleInputChange("name", "Valid Name");
    });
    act(() => {
      result.current.submit();
    });

    expect(result.current.errors.location_id).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("calls onSubmit when form is valid", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    act(() => {
      result.current.handleInputChange("name", "Valid Item");
      result.current.handleInputChange("location_id", "loc-1");
    });
    act(() => {
      result.current.submit();
    });

    expect(onSubmit).toHaveBeenCalledOnce();
  });

  // An emptied field hands over no quantity at all, and a payload without
  // one is saved by the server's default as a single piece. The required
  // check is what stands in front of that; this pins it.
  it("refuses an emptied quantity instead of saving one", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    act(() => {
      result.current.handleInputChange("name", "Valid Item");
      result.current.handleInputChange("location_id", "loc-1");
      // What the number field hands over when it is cleared.
      result.current.handleInputChange("quantity", null);
    });
    act(() => {
      result.current.submit();
    });

    expect(result.current.errors.quantity).toBeTruthy();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("takes a quantity of zero as a quantity", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    act(() => {
      result.current.handleInputChange("name", "Valid Item");
      result.current.handleInputChange("location_id", "loc-1");
      result.current.handleInputChange("quantity", "0");
    });
    act(() => {
      result.current.submit();
    });

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit.mock.calls[0][0].quantity).toBe(0);
  });
});

describe("useItemForm — changing the unit", () => {
  it("converts the quantity when the new unit measures the same thing", async () => {
    const { result } = renderItemForm({
      ...defaultProps,
      initialData: { name: "Sugar", quantity: "500", uom_id: GRAM },
    });
    await waitForUomCategory(result, "Weight");

    act(() => {
      result.current.handleInputChange("uom_id", KILOGRAM);
    });

    // 500 g is half a kilogram, not 500 kg
    expect(result.current.formData.quantity).toBe("0.5");
  });

  it("converts back the other way", async () => {
    const { result } = renderItemForm({
      ...defaultProps,
      initialData: { name: "Sugar", quantity: "0.5", uom_id: KILOGRAM },
    });
    await waitForUomCategory(result, "Weight");

    act(() => {
      result.current.handleInputChange("uom_id", GRAM);
    });

    expect(result.current.formData.quantity).toBe("500");
  });

  it("clears the quantity when the new unit measures something else", async () => {
    const { result } = renderItemForm({
      ...defaultProps,
      initialData: { name: "Sugar", quantity: "500", uom_id: GRAM },
    });
    await waitForUomCategory(result, "Weight");

    act(() => {
      result.current.handleInputChange("uom_id", PIECE);
    });

    // Grams do not convert to pieces, so there is nothing to carry over
    expect(result.current.formData.quantity).toBe("");
    // …and silently emptying a field the user filled in is how a saved item
    // ends up with no quantity, so the form has to say it happened.
    expect(toast.info).toHaveBeenCalledTimes(1);
    const [message] = vi.mocked(toast.info).mock.calls[0];
    expect(message).toMatch(/quantity/i);
    // …in the user's language, not as the raw key
    expect(message).not.toContain("items:");
  });

  it("says nothing when the quantity survives the change", async () => {
    const { result } = renderItemForm({
      ...defaultProps,
      initialData: { name: "Sugar", quantity: "500", uom_id: GRAM },
    });
    await waitForUomCategory(result, "Weight");

    act(() => {
      result.current.handleInputChange("uom_id", KILOGRAM);
    });

    expect(result.current.formData.quantity).toBe("0.5");
    expect(toast.info).not.toHaveBeenCalled();
  });

  it("leaves an empty quantity empty", async () => {
    const { result } = renderItemForm({
      ...defaultProps,
      initialData: { name: "Sugar", quantity: "", uom_id: GRAM },
    });
    await waitForUomCategory(result, "Weight");

    act(() => {
      result.current.handleInputChange("uom_id", KILOGRAM);
    });

    expect(result.current.formData.quantity).toBe("");
  });
});

describe("useItemForm — unit weight in the submit payload", () => {
  // ADR-015: the form edits the weight of one unit, which the API records on
  // the product template. The item's own weight is a computed total and is
  // never sent back.
  it("sends the entered weight as the product's unit weight", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      initialData: {
        name: "Product",
        location_id: "loc-1",
        quantity: "2",
        uom_id: PIECE,
      },
    });
    await waitForUomCategory(result, "Count");

    act(() => {
      result.current.handleInputChange("weight", "500");
      result.current.handleInputChange("weight_uom_id", GRAM);
    });
    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.weight_value).toBe(500);
    expect(payload.weight_uom_id).toBe(GRAM);
    expect("weight" in payload).toBe(false);
  });

  it("reads the unit weight back from the product template", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      initialData: apiItem({
        name: "Milk 500 g",
        location_id: "loc-1",
        quantity: 3,
        uom_id: PIECE,
        weight: 1.5, // computed total from the API — must not reach the form
        template: { weight_value: 500, weight_uom_id: GRAM },
      }),
    });
    await waitForUomCategory(result, "Count");

    expect(result.current.formData.weight).toBe("500");
    expect(result.current.formData.weight_uom_id).toBe(GRAM);
  });

  it("saving an untouched item sends the same unit weight back", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      initialData: apiItem({
        name: "Milk 500 g",
        location_id: "loc-1",
        quantity: 3,
        uom_id: PIECE,
        weight: 1.5,
        template: { weight_value: 500, weight_uom_id: GRAM },
      }),
    });
    await waitForUomCategory(result, "Count");

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.weight_value).toBe(500);
  });

  it("sends no unit weight when the field is empty", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      initialData: {
        name: "Screwdriver",
        location_id: "loc-1",
        quantity: "2",
        uom_id: PIECE,
      },
    });
    await waitForUomCategory(result, "Count");

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect("weight_value" in payload).toBe(false);
  });

  it("drops the unit weight when the unit makes the field irrelevant", async () => {
    // A product counted in grams has no per-unit weight — the quantity is the
    // weight, and computeFieldDefinitions hides the field.
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      initialData: {
        name: "Sugar",
        location_id: "loc-1",
        quantity: "500",
        uom_id: GRAM,
        weight: "500",
      },
    });
    await waitForUomCategory(result, "Weight");

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect("weight_value" in payload).toBe(false);
  });
});

describe("useItemForm — submit payload cleaning", () => {
  it("removes empty string fields from submission", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      initialData: {
        name: "Item",
        location_id: "loc-1",
        brand: "",
        description: "",
      },
    });

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect("brand" in payload).toBe(false);
    expect("description" in payload).toBe(false);
  });
});

describe("useItemForm — the category the form draws is the one it sends", () => {
  // A food category declares nothing: no field_definitions, no context.
  // The picker offers it, so the payload owes it — this is the record that
  // used to come back with `category: null` while the form said "added".
  it("sends a category the profile does not declare", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      categories: [
        {
          id: "cat-food",
          name: "Food",
          is_active: true,
          is_module_owned: false,
          field_definitions: [],
          context_tag: null,
        },
      ],
      initialData: {
        name: "Butter",
        location_id: "loc-1",
        category_id: "cat-food",
      },
    });

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.category_id).toBe("cat-food");
  });

  // An equipment-style declaration says the same thing the default now does,
  // so it must not behave differently — three inputs, one outcome.
  it("sends it the same way when the category declares the field visible", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      categories: [
        {
          name: "Test category",
          is_active: true,
          is_module_owned: false,
          id: "cat-eq",
          field_definitions: [
            {
              key: "category_id",
              label: "itemCategory",
              type: "select",
              required: false,
              is_system: false,
              visible: true,
            },
          ],
          context_tag: "equipment",
        },
      ],
      initialData: {
        name: "Laptop",
        location_id: "loc-1",
        category_id: "cat-eq",
      },
    });

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.category_id).toBe("cat-eq");
  });

  it("still says nothing about a category the category itself hides", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      categories: [
        {
          name: "Test category",
          is_active: true,
          is_module_owned: false,
          id: "cat-hidden",
          field_definitions: [
            {
              key: "category_id",
              label: "itemCategory",
              type: "select",
              required: false,
              is_system: false,
              visible: false,
            },
          ],
          context_tag: null,
        },
      ],
      initialData: {
        name: "Item",
        location_id: "loc-1",
        category_id: "cat-hidden",
      },
    });

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect("category_id" in payload).toBe(false);
  });

  // The edit dialog passes no categories into the hook at all — the payload
  // must still carry the change, because the default answer is the same one
  // the picker rendered.
  it("sends the changed category when editing", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      form: "item_edit",
      initialData: {
        name: "Item",
        location_id: "loc-1",
        category_id: "cat-old",
      },
    });

    act(() => {
      result.current.handleInputChange("category_id", "cat-new");
    });
    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.category_id).toBe("cat-new");
  });

  // Picking "Cheese" used to take the expiry date out of the form and out of
  // the submission in the same frame, without a word. The field is
  // visible again — and a category change that would still drop a filled
  // value has to name it before anything is written.
  it("keeps the expiry date in the payload for a category the food profile seeds", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      categories: [
        {
          name: "Test category",
          is_active: true,
          is_module_owned: false,
          id: "cat-cheese",
          field_definitions: [],
          context_tag: "cold_storage",
        },
      ],
      initialData: {
        name: "Gouda",
        location_id: "loc-1",
        category_id: "cat-cheese",
        expiry_date: "2026-12-31",
      },
    });

    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.expiry_date).toBe("2026-12-31");
  });

  it("names the filled fields a category change would drop", () => {
    const { result } = renderItemForm({
      ...defaultProps,
      categories: [
        {
          id: "cat-none",
          name: "No category",
          is_active: true,
          is_module_owned: false,
          field_definitions: [],
          context_tag: null,
        },
        {
          id: "cat-eq",
          name: "Equipment",
          is_active: true,
          is_module_owned: true,
          field_definitions: [],
          context_tag: "equipment",
        },
      ],
      initialData: {
        name: "Butter",
        category_id: "cat-none",
        expiry_date: "2026-12-31",
      },
    });

    act(() => {
      result.current.handleInputChange("category_id", "cat-eq");
    });

    expect(toast.warning).toHaveBeenCalledTimes(1);
    const [message] = vi.mocked(toast.warning).mock.calls[0];
    expect(message).toMatch(/expiry/i);
    // In the user's language, not as the raw key.
    expect(message).not.toContain("items:");
  });

  it("says nothing when the change drops nothing that was filled", () => {
    const { result } = renderItemForm({
      ...defaultProps,
      categories: [
        {
          id: "cat-none",
          name: "No category",
          is_active: true,
          is_module_owned: false,
          field_definitions: [],
          context_tag: null,
        },
        {
          id: "cat-eq",
          name: "Equipment",
          is_active: true,
          is_module_owned: true,
          field_definitions: [],
          context_tag: "equipment",
        },
      ],
      initialData: {
        name: "Butter",
        category_id: "cat-none",
        expiry_date: "",
      },
    });

    act(() => {
      result.current.handleInputChange("category_id", "cat-eq");
    });

    expect(toast.warning).not.toHaveBeenCalled();
  });

  it("does not warn when the new category keeps the fields visible", () => {
    const { result } = renderItemForm({
      ...defaultProps,
      categories: [
        {
          id: "cat-none",
          name: "No category",
          is_active: true,
          is_module_owned: false,
          field_definitions: [],
          context_tag: null,
        },
        {
          name: "Test category",
          is_active: true,
          is_module_owned: false,
          id: "cat-cheese",
          field_definitions: [],
          context_tag: "cold_storage",
        },
      ],
      initialData: {
        name: "Butter",
        category_id: "cat-none",
        expiry_date: "2026-12-31",
      },
    });

    act(() => {
      result.current.handleInputChange("category_id", "cat-cheese");
    });

    expect(toast.warning).not.toHaveBeenCalled();
  });
});

describe("useItemForm — the purchase price follows the inventory-value switch", () => {
  it("hides purchase_price where the inventory value is not shown", () => {
    inventoryValue.shown = false;
    const { result } = renderItemForm(defaultProps);

    const price = result.current.fieldDefinitions.find(
      (f) => f.key === "purchase_price",
    );
    expect(price?.visible).toBe(false);
  });

  it("offers purchase_price where the inventory value is shown", () => {
    const { result } = renderItemForm(defaultProps);

    const price = result.current.fieldDefinitions.find(
      (f) => f.key === "purchase_price",
    );
    expect(price?.visible).toBe(true);
  });
});

describe("useItemForm — add and edit compute the same fields", () => {
  const laptop = {
    id: "77",
    name: "Laptop",
    code: "LAPTOP",
    sort_order: 2,
    field_definitions: [
      {
        key: "asset_tag",
        type: "text",
        label: "Asset Tag",
        visible: true,
        required: false,
        is_system: true,
      },
    ],
  } as unknown as NonNullable<
    Parameters<typeof useItemForm>[0]["categories"]
  >[number];
  const record = { name: "Dell XPS", category_id: "77" };

  const keys = (form: "item_create" | "item_edit", withCategories = true) => {
    const { result } = renderItemForm({
      ...defaultProps,
      form,
      initialData: record,
      categories: withCategories ? [laptop] : [],
    });
    return result.current.fieldDefinitions.map((d) => d.key);
  };

  // The same record must yield the same field set whichever door it comes
  // through; a caller that stops passing `categories` to either door shows
  // here as a missing category field.
  it("gives one record the same fields on the add and the edit path", () => {
    const add = keys("item_create");
    expect(add).toContain("asset_tag");
    expect(keys("item_edit")).toEqual(add);
  });

  it("notices a door that drops the categories", () => {
    expect(keys("item_edit", false)).not.toEqual(keys("item_create"));
  });
});

describe("useItemForm — a refused submit", () => {
  it("moves focus to the invalid fields and sends nothing", () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({ onSubmit });

    act(() => result.current.submit());

    expect(onSubmit).not.toHaveBeenCalled();
    expect(focusFirstInvalidField).toHaveBeenCalledTimes(1);
    expect(vi.mocked(focusFirstInvalidField).mock.calls[0][0]).toEqual(
      expect.arrayContaining(["name"]),
    );
  });
});

describe("useItemForm — the product's SKU", () => {
  // The SKU is the product's, kept on its template: no catalogue form could
  // set or change it before.
  it("sends a SKU typed on the add form", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      initialData: {
        name: "Hex bolt",
        location_id: "loc-1",
        quantity: "2",
        uom_id: PIECE,
      },
    });
    await waitForUomCategory(result, "Count");

    act(() => {
      result.current.handleInputChange("sku", "BOLT-M8");
    });
    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.sku).toBe("BOLT-M8");
  });

  it("shows the product's SKU on the edit form and sends a changed one", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      initialData: apiItem({
        name: "Hex bolt",
        location_id: "loc-1",
        quantity: 3,
        uom_id: PIECE,
        template: { sku: "BOLT-M8" },
      }),
    });
    await waitForUomCategory(result, "Count");
    expect(result.current.formData.sku).toBe("BOLT-M8");

    act(() => {
      result.current.handleInputChange("sku", "BOLT-M8-ZN");
    });
    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.sku).toBe("BOLT-M8-ZN");
  });

  it("clears the SKU when the field is emptied on an edit", async () => {
    const onSubmit = vi.fn();
    const { result } = renderItemForm({
      onSubmit,
      form: "item_edit",
      initialData: apiItem({
        name: "Hex bolt",
        location_id: "loc-1",
        quantity: 3,
        uom_id: PIECE,
        template: { sku: "BOLT-M8" },
      }),
    });
    await waitForUomCategory(result, "Count");

    act(() => {
      result.current.handleInputChange("sku", "");
    });
    act(() => {
      result.current.submit();
    });

    const payload = onSubmit.mock.calls[0][0] as Record<string, unknown>;
    expect(payload.sku).toBeNull();
  });
});
