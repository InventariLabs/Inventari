import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import i18n from "@/i18n/config";
import UnifiedFieldRenderer from "./UnifiedFieldRenderer";
import type { FieldDefinition } from "@/types";

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

const textFieldDef: FieldDefinition = {
  key: "brand",
  type: "text",
  label: "Brand",
  visible: true,
  required: false,
  is_system: false,
  is_custom: false,
};

const dateFieldDef: FieldDefinition = {
  key: "expiry_date",
  type: "date",
  label: "Expiry Date",
  visible: true,
  required: false,
  is_system: false,
  is_custom: false,
};

const numberFieldDef: FieldDefinition = {
  key: "quantity",
  type: "number",
  label: "Quantity",
  visible: true,
  required: true,
  is_system: false,
  is_custom: false,
};

const unitFieldDef: FieldDefinition = {
  key: "unit",
  type: "text",
  label: "Unit",
  visible: true,
  required: false,
  is_system: false,
  is_custom: false,
};

const notesFieldDef: FieldDefinition = {
  key: "notes",
  type: "textarea",
  label: "Notes",
  visible: true,
  required: false,
  is_system: false,
  is_custom: false,
};

const priceFieldDef: FieldDefinition = {
  key: "purchase_price",
  type: "money",
  label: "Purchase Price",
  visible: true,
  required: false,
  is_system: false,
  is_custom: false,
};

describe("UnifiedFieldRenderer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when fieldDefinitions is empty", () => {
    const { container } = render(
      <UnifiedFieldRenderer
        fieldDefinitions={[]}
        formData={{}}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders text field with label", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[textFieldDef]}
        formData={{ brand: "Nestle" }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByDisplayValue("Nestle")).toBeInTheDocument();
  });

  it("associates each field label with its control", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[
          textFieldDef,
          notesFieldDef,
          priceFieldDef,
          dateFieldDef,
        ]}
        formData={{ brand: "Nestle" }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByLabelText("Brand")).toHaveValue("Nestle");
    expect(screen.getByLabelText("Notes").tagName).toBe("TEXTAREA");
    expect(screen.getByLabelText("Purchase Price")).toHaveAttribute(
      "type",
      "number",
    );
    // The date picker's control is its trigger button, which a label can name
    // just as well as an input.
    expect(screen.getByLabelText("Expiry Date").tagName).toBe("BUTTON");
  });

  it("keeps labels apart when the renderer appears twice on a page", () => {
    render(
      <>
        <UnifiedFieldRenderer
          fieldDefinitions={[textFieldDef]}
          formData={{ brand: "First" }}
          onChange={vi.fn()}
        />
        <UnifiedFieldRenderer
          fieldDefinitions={[textFieldDef]}
          formData={{ brand: "Second" }}
          onChange={vi.fn()}
        />
      </>,
      { wrapper: createWrapper() },
    );
    const [first, second] = screen.getAllByLabelText("Brand");
    expect(first).toHaveValue("First");
    expect(second).toHaveValue("Second");
  });

  it("renders date field", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[dateFieldDef]}
        formData={{ expiry_date: "2026-12-31" }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    // The shared DateInput renders a trigger, not a native input
    expect(screen.getByText(/Dec 31, 2026/)).toBeInTheDocument();
  });

  it("renders multiple fields", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[textFieldDef, numberFieldDef]}
        formData={{ brand: "Test", quantity: "5" }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByDisplayValue("Test")).toBeInTheDocument();
    expect(screen.getByDisplayValue("5")).toBeInTheDocument();
  });

  it("calls onChange when text field value changes", () => {
    const onChange = vi.fn();
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[textFieldDef]}
        formData={{ brand: "" }}
        onChange={onChange}
      />,
      { wrapper: createWrapper() },
    );
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "NewBrand" } });
    expect(onChange).toHaveBeenCalledWith(
      "brand",
      "NewBrand",
      expect.anything(),
    );
  });

  it("shows validation error for required field", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[numberFieldDef]}
        formData={{ quantity: "" }}
        onChange={vi.fn()}
        errors={{ quantity: "Quantity is required" }}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Quantity is required")).toBeInTheDocument();
  });
});

// ── Money + multi-select + boolean renderers ──────────────

const moneyFieldDef: FieldDefinition = {
  key: "deposit",
  type: "money",
  label: "Deposit",
  default_currency: "EUR",
  visible: true,
  required: false,
  is_system: false,
  is_custom: true,
};

const multiSelectFieldDef: FieldDefinition = {
  key: "allergens",
  type: "multi-select",
  label: "Allergens",
  options: ["Gluten", "Lactose", "Nuts"],
  visible: true,
  required: false,
  is_system: false,
  is_custom: true,
};

const booleanFieldDef: FieldDefinition = {
  key: "lactose_free",
  type: "boolean",
  label: "Lactose free",
  visible: true,
  required: false,
  is_system: false,
  is_custom: true,
};

describe("UnifiedFieldRenderer — money, multi-select and boolean types", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders money field with amount + currency", () => {
    const onChange = vi.fn();
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[moneyFieldDef]}
        formData={{
          metadata: { deposit: { amount: "10.50", currency: "EUR" } },
        }}
        onChange={onChange}
      />,
      { wrapper: createWrapper() },
    );
    // Amount input shows "10.50"; default_currency is rendered as the
    // currency symbol/code on the right.
    expect(screen.getByDisplayValue("10.50")).toBeInTheDocument();
    // The currency chip from default_currency must be present.
    expect(screen.getByText("EUR")).toBeInTheDocument();
  });

  it("emits {amount, currency} object when money amount changes", () => {
    const onChange = vi.fn();
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[moneyFieldDef]}
        formData={{ metadata: {} }}
        onChange={onChange}
      />,
      { wrapper: createWrapper() },
    );
    const amountInput = screen.getByRole("spinbutton");
    fireEvent.change(amountInput, { target: { value: "12.34" } });
    expect(onChange).toHaveBeenCalledWith(
      "deposit",
      { amount: "12.34", currency: "EUR" },
      expect.anything(),
    );
  });

  it("renders multi-select with options", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[multiSelectFieldDef]}
        formData={{ metadata: { allergens: ["Gluten"] } }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    // Each option renders as a toggle/checkbox.
    expect(screen.getByText("Gluten")).toBeInTheDocument();
    expect(screen.getByText("Lactose")).toBeInTheDocument();
    expect(screen.getByText("Nuts")).toBeInTheDocument();
  });

  it("emits string[] when multi-select value changes", () => {
    const onChange = vi.fn();
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[multiSelectFieldDef]}
        formData={{ metadata: { allergens: [] } }}
        onChange={onChange}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Gluten"));
    expect(onChange).toHaveBeenCalledWith(
      "allergens",
      ["Gluten"],
      expect.anything(),
    );
  });

  it("renders boolean field as a switch/checkbox", () => {
    const onChange = vi.fn();
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[booleanFieldDef]}
        formData={{ metadata: { lactose_free: false } }}
        onChange={onChange}
      />,
      { wrapper: createWrapper() },
    );
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(onChange).toHaveBeenCalledWith(
      "lactose_free",
      true,
      expect.anything(),
    );
  });
});

// ── "Configure category fields" link ─────────────────────

const categoryFieldDef: FieldDefinition = {
  key: "category_id",
  type: "text",
  label: "Category",
  visible: true,
  required: false,
  is_system: false,
  is_custom: false,
};

const sampleCategory = {
  id: "cat-1",
  organization_id: "o1",
  name: "Glass bottles",
  code: "glass_bottles",
  icon: null,
  sort_order: 1,
  is_active: true,
  context_tag: null,
  is_module_owned: false,
  module_name: null,
  meta_data: null,
  field_definitions: [],
};

describe("UnifiedFieldRenderer — Configure category fields link", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the link when a category is selected and onConfigureCategoryFields is set", () => {
    const onConfigure = vi.fn();
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[categoryFieldDef]}
        formData={{ category_id: "cat-1" }}
        onChange={vi.fn()}
        categories={[sampleCategory]}
        onConfigureCategoryFields={onConfigure}
      />,
      { wrapper: createWrapper() },
    );
    const link = screen.getByTestId("configure-category-fields");
    fireEvent.click(link);
    expect(onConfigure).toHaveBeenCalledWith("cat-1");
  });

  it("names the category combobox with its visible label", () => {
    // The renderer used to leave `htmlFor` off this one because the trigger
    // named itself with `aria-label`. That `aria-label` is gone, so the id has
    // to reach the trigger — a `<button>` is labelable, so `htmlFor` works.
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[categoryFieldDef]}
        formData={{ category_id: "cat-1" }}
        onChange={vi.fn()}
        categories={[sampleCategory]}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      screen.getByRole("combobox", { name: "Category" }),
    ).toBeInTheDocument();
  });

  it("does not show the link when no category is selected", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[categoryFieldDef]}
        formData={{ category_id: "" }}
        onChange={vi.fn()}
        categories={[sampleCategory]}
        onConfigureCategoryFields={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      screen.queryByTestId("configure-category-fields"),
    ).not.toBeInTheDocument();
  });

  it("shows a quantity of zero as zero, not as an empty field", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[numberFieldDef, unitFieldDef]}
        // The number arrives from the item record, not as a string — and
        // `0 || ""` is the empty string.
        formData={{ quantity: 0 }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );

    expect(screen.getByDisplayValue("0")).toBeInTheDocument();
  });
});

describe("a system field's label speaks the reader's language", () => {
  const originalLanguage = i18n.language;
  afterEach(async () => {
    await i18n.changeLanguage(originalLanguage);
  });

  const assetTagField: FieldDefinition = {
    key: "asset_tag",
    type: "text",
    label: "Asset Tag",
    visible: true,
    required: false,
    is_custom: false,
    is_system: true,
  };

  it("shows a seeded field's label in the interface language", async () => {
    await i18n.changeLanguage("pl");
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[
          assetTagField,
          {
            key: "resolution",
            type: "text",
            label: "Resolution",
            visible: true,
            required: false,
            is_custom: false,
            is_system: true,
          },
          {
            key: "freeze_date",
            type: "date",
            label: "Freeze date",
            visible: true,
            required: false,
            is_custom: false,
            is_system: true,
          },
        ]}
        formData={{}}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(await screen.findByText("Numer inwentarzowy")).toBeInTheDocument();
    expect(screen.getByText("Rozdzielczość")).toBeInTheDocument();
    expect(screen.getByText("Data zamrożenia")).toBeInTheDocument();
    expect(screen.queryByText("Asset Tag")).toBeNull();
    expect(screen.queryByText("Freeze date")).toBeNull();
  });

  it("keeps a user field's own words even when its key is a known one", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[
          { ...assetTagField, is_system: false, label: "Mój własny tag" },
        ]}
        formData={{}}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Mój własny tag")).toBeInTheDocument();
    expect(screen.queryByText("Numer inwentarzowy")).toBeNull();
  });
});

/**
 * Measured against the code before `SelectField` existed, when `select` fell
 * through to the default text input: **2 of these failed, 21 other tests in
 * this file passed.**
 *
 * Red on the old code — these discriminate:
 *   - "renders the declared choices as a picker, not as free text" (the
 *     control was an INPUT)
 *   - "keeps a stored value the option list does not contain"
 *
 * Green on BOTH sides — recorded as such rather than left to read as proof:
 *   - "emits the option the reader picked"
 * `fireEvent.change` on a text input emits the same value a `<select>` does,
 * so that one pins the onChange contract, not the fix.
 *
 * "emits the unset shape when the reader clears an optional field" started as
 * this block's empty-choice test and expected `""` back then, which made it
 * green on both sides too. It expects `null` now — the shape the backend
 * accepts as a clear — and is red on the old control for that reason.
 */
describe("a select field offers the choices it was given", () => {
  const originalLanguage = i18n.language;
  afterEach(async () => {
    await i18n.changeLanguage(originalLanguage);
  });

  const statusField: FieldDefinition = {
    key: "equipment_status",
    type: "select",
    label: "Status",
    visible: true,
    required: false,
    is_system: true,
    options: ["AVAILABLE", "DEPLOYED", "MAINTENANCE", "RETIRED"],
  };

  it("renders the declared choices as a picker, not as free text", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[statusField]}
        formData={{ metadata: { equipment_status: "DEPLOYED" } }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    const control = screen.getByLabelText("Status");
    expect(control.tagName).toBe("SELECT");
    expect(control).toHaveValue("DEPLOYED");
    for (const opt of statusField.options ?? []) {
      expect(screen.getByRole("option", { name: opt })).toBeInTheDocument();
    }
  });

  it("emits the option the reader picked", () => {
    const onChange = vi.fn();
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[statusField]}
        formData={{ metadata: { equipment_status: "AVAILABLE" } }}
        onChange={onChange}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "MAINTENANCE" },
    });
    expect(onChange).toHaveBeenCalledWith(
      "equipment_status",
      "MAINTENANCE",
      expect.anything(),
    );
  });

  // The picker is arriving over data that a free-text input wrote for as long
  // as `select` fell through to it, and over legacy rows whose options list is
  // empty. A `<select>` that does not carry the stored value silently reports
  // the first option instead — the record would change its status by being
  // opened. Keep the value, and say on screen that the list does not know it.
  it("keeps a stored value the option list does not contain", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[statusField]}
        formData={{ metadata: { equipment_status: "BORROWED BY ANNA" } }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByLabelText("Status")).toHaveValue("BORROWED BY ANNA");
    expect(
      screen.getByRole("option", { name: /BORROWED BY ANNA/ }),
    ).toBeInTheDocument();
  });

  // The words belong to whoever declares the field. `options_i18n` names a
  // fully-qualified key per option — the same convention `label_key` already
  // uses for permissions and AI purposes — so the equipment module's own
  // `equipment:status.*` answers here, instead of the core form keeping a
  // second dictionary of the same four words.
  it("reads a platform option in the declaring module's own words", async () => {
    // The `equipment` catalog arrives with the test setup's i18next
    // resources — the production path is the i18n backend, which the unit
    // suite replaces with the same bundles preloaded.
    await i18n.changeLanguage("pl");
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[
          {
            ...statusField,
            options_i18n: {
              AVAILABLE: "equipment:status.available",
              DEPLOYED: "equipment:status.deployed",
              MAINTENANCE: "equipment:status.maintenance",
              RETIRED: "equipment:status.retired",
            },
          },
        ]}
        formData={{ metadata: { equipment_status: "AVAILABLE" } }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      await screen.findByRole("option", { name: "Dostępny" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "W serwisie" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "AVAILABLE" })).toBeNull();
  });

  it("keeps an option's own word when the definition names no key for it", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[
          {
            ...statusField,
            is_system: false,
            options: ["Na chodzie", "Do naprawy"],
          },
        ]}
        formData={{ metadata: { equipment_status: "Na chodzie" } }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(
      screen.getByRole("option", { name: "Na chodzie" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Do naprawy" }),
    ).toBeInTheDocument();
  });

  // Clearing an optional field has to be a save the backend accepts. Its
  // select validator reads `""` as a value and refuses it ("value '' is not
  // in declared options"), while `null` is the "not set" sentinel it takes
  // for an optional field — so the empty entry emits that, not empty string.
  it("emits the unset shape when the reader clears an optional field", () => {
    const onChange = vi.fn();
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[statusField]}
        formData={{ metadata: { equipment_status: "DEPLOYED" } }}
        onChange={onChange}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "" },
    });
    expect(onChange).toHaveBeenCalledWith(
      "equipment_status",
      null,
      expect.anything(),
    );
  });
});

// The words belong to whoever declares the field, and the declaration at
// `schemas/category.py` says `select` / `multi-select` — so the checkbox row
// has to resolve `options_i18n` exactly as the picker does, or the contract
// is wider than either consumer.
describe("a multi-select field reads an option in the declaring module's own words", () => {
  const originalLanguage = i18n.language;
  afterEach(async () => {
    await i18n.changeLanguage(originalLanguage);
  });

  it("translates an option the definition names a key for", async () => {
    await i18n.changeLanguage("pl");
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[
          {
            key: "equipment_states",
            type: "multi-select",
            label: "States",
            visible: true,
            required: false,
            is_custom: true,
            is_system: false,
            options: ["AVAILABLE", "MAINTENANCE"],
            options_i18n: {
              AVAILABLE: "equipment:status.available",
              MAINTENANCE: "equipment:status.maintenance",
            },
          },
        ]}
        formData={{ metadata: { equipment_states: ["AVAILABLE"] } }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(await screen.findByText("Dostępny")).toBeInTheDocument();
    expect(screen.getByText("W serwisie")).toBeInTheDocument();
    expect(screen.queryByText("AVAILABLE")).toBeNull();
  });

  it("keeps an option's own word when the definition names no key for it", () => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[
          {
            key: "allergens",
            type: "multi-select",
            label: "Allergens",
            visible: true,
            required: false,
            is_custom: true,
            is_system: false,
            options: ["Gluten", "Lactose"],
          },
        ]}
        formData={{ metadata: { allergens: [] } }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Gluten")).toBeInTheDocument();
    expect(screen.getByText("Lactose")).toBeInTheDocument();
  });
});
