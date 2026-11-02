import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryWrapper } from "@/test/queryWrapper";
import type { FieldDefinition } from "@/types";

// ── mocks ──────────────────────────────────────────────────────────────────────

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/ui/Button", () => ({
  default: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props} />
  ),
}));

// ── ProductFormContent ────────────────────────────────────────────────────────
// NOTE: ProductFormContent is a complex form — we import lazily to avoid heavy
// dependency chain issues and rely on mocks for sub-components.

vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({ placeholder }: { placeholder?: string }) => (
    <div data-testid="searchable-combobox">{placeholder}</div>
  ),
}));

// Path is relative to this test file, not to ProductFormContent — the old
// "../UnifiedFieldRenderer" resolved to a module nobody imports, so the mock
// silently did nothing and the real renderer went looking for a QueryClient.
vi.mock("./UnifiedFieldRenderer", () => ({
  default: () => <div data-testid="unified-field-renderer" />,
}));

vi.mock("@/utils/helpers", () => ({
  getStorageLocationPath: vi.fn((s) => s?.name ?? ""),
  formatDate: vi.fn(() => ""),
  isExpired: vi.fn(() => false),
  isExpiringSoon: vi.fn(() => false),
}));

// Dynamic import to avoid hoisting issues with the vi.mock calls above
const { default: ProductFormContent } =
  await import("./items/ProductFormContent");

// The location field searches the server, so the form needs a query client.
const renderForm = (ui: React.ReactElement) =>
  render(<QueryWrapper>{ui}</QueryWrapper>);

function makeField(overrides: Partial<FieldDefinition> = {}): FieldDefinition {
  return {
    key: "name",
    label: "Product name",
    type: "text",
    visible: true,
    required: true,
    is_system: false,
    ...overrides,
  };
}

describe("ProductFormContent", () => {
  const onChange = vi.fn();

  beforeEach(() => {
    onChange.mockClear();
  });

  it("renders item name label and input", () => {
    renderForm(
      <ProductFormContent
        formData={{ name: "" }}
        onChange={onChange}
        errors={{}}
        fieldDefinitions={[makeField()]}
      />,
    );
    expect(screen.getByLabelText(/Product name/i)).toBeInTheDocument();
  });

  it("shows name input with current value", () => {
    renderForm(
      <ProductFormContent
        formData={{ name: "Butter" }}
        onChange={onChange}
        errors={{}}
        fieldDefinitions={[makeField()]}
      />,
    );
    expect(screen.getByDisplayValue("Butter")).toBeInTheDocument();
  });

  it("calls onChange when name input changes", () => {
    renderForm(
      <ProductFormContent
        formData={{ name: "" }}
        onChange={onChange}
        errors={{}}
        fieldDefinitions={[makeField()]}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: /Product name/i }), {
      target: { value: "Cheese" },
    });
    expect(onChange).toHaveBeenCalledWith("name", "Cheese");
  });

  it("renders error message when errors.name is set", () => {
    renderForm(
      <ProductFormContent
        formData={{ name: "" }}
        onChange={onChange}
        errors={{ name: "Name is required" }}
        fieldDefinitions={[makeField()]}
      />,
    );
    expect(screen.getByText("Name is required")).toBeInTheDocument();
  });
});
