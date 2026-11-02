import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@/i18n/config";
import type { FieldDefinition } from "@/types";
import { BarcodeField } from "./BarcodeField";

const generateBarcode = vi.fn();
vi.mock("@/lib/api/productTemplates", () => ({
  productTemplatesApi: { generateBarcode: () => generateBarcode() },
}));

const barcodeField: FieldDefinition = {
  key: "barcode",
  type: "text",
  label: "fields.barcode",
  visible: true,
  required: false,
  is_system: true,
  is_custom: false,
};

function renderField(
  value: string,
  onChange = vi.fn(),
  field: FieldDefinition = barcodeField,
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <BarcodeField field={field} value={value} onChange={onChange} />
    </QueryClientProvider>,
  );
  return onChange;
}

describe("BarcodeField", () => {
  beforeEach(() => {
    generateBarcode.mockReset();
  });

  it("fills an empty field with the generated code", async () => {
    generateBarcode.mockResolvedValue("2000000000015");
    const onChange = renderField("");

    fireEvent.click(screen.getByRole("button", { name: "Generate code" }));

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("2000000000015"));
    expect(generateBarcode).toHaveBeenCalledTimes(1);
  });

  it("offers nothing to replace a code the product already has", () => {
    renderField("5901234123457");

    expect(
      screen.queryByRole("button", { name: "Generate code" }),
    ).not.toBeInTheDocument();
  });

  it("does not invite a scan: this field has no camera beside it", () => {
    renderField("", vi.fn(), {
      ...barcodeField,
      placeholder: "placeholders.barcode",
    });

    expect(screen.getByPlaceholderText("Type the code")).toBeInTheDocument();
  });
});
