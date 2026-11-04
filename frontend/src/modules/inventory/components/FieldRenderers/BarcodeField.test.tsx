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

// The camera is a live device; what the field does with a read is tested.
vi.mock("./ScanCodeButton", () => ({
  ScanCodeButton: ({
    label,
    onCode,
  }: {
    label: string;
    onCode: (code: string) => void;
  }) => (
    <button type="button" onClick={() => onCode("5901234123457")}>
      {label}
    </button>
  ),
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

  it("reads the code printed on the product with the camera", async () => {
    const onChange = renderField("");

    fireEvent.click(
      await screen.findByRole("button", { name: "Scan product code" }),
    );

    expect(onChange).toHaveBeenCalledWith("5901234123457");
  });

  it("says what a generated code is beside the button and with the code", () => {
    const { unmount } = render(
      <QueryClientProvider client={new QueryClient()}>
        <BarcodeField field={barcodeField} value="" onChange={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(
      screen.getByRole("button", { name: "Generate code" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/valid only inside the organization/),
    ).toBeVisible();
    unmount();

    renderField("2000000000015");
    expect(
      screen.getByText(/valid only inside the organization/),
    ).toBeVisible();
  });

  it("keeps the hint off a manufacturer's code", () => {
    renderField("5901234123457");

    expect(
      screen.queryByText(/valid only inside the organization/),
    ).not.toBeInTheDocument();
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
