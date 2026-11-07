import { useState } from "react";
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

  // The hint stood as a plain paragraph: a screen reader on the field never
  // heard it, so it is now the input's description.
  it("describes, under an empty field, the code the button gives", () => {
    renderField("");

    expect(
      screen.getByRole("textbox", { name: "Product code" }),
    ).toHaveAccessibleDescription(
      /^“Generate code” gives an in-house code starting with 20/,
    );
  });

  // A 13-digit code starting with 20 may be another company's in-store code
  // typed by hand; the form cannot tell, so the sentence holds for both.
  it("describes a code in the in-house range without claiming who made it", () => {
    renderField("2000000000015");

    const input = screen.getByRole("textbox", { name: "Product code" });
    expect(input).toHaveAccessibleDescription(
      /valid only inside the business that assigned it/,
    );
    expect(input).not.toHaveAccessibleDescription(/organization/);
  });

  it("keeps the hint off a manufacturer's code", () => {
    renderField("5901234123457");

    expect(screen.queryByText(/GS1/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Product code" }),
    ).not.toHaveAccessibleDescription();
  });

  // The hint went on the first keystroke of a typed code, and everything
  // below the field moved up by its height. Its place stays, empty and out
  // of the accessibility tree, for as long as the form is open.
  it("keeps the hint's place when the first character of a code is typed", () => {
    function Controlled() {
      const [code, setCode] = useState("");
      return (
        <BarcodeField
          field={barcodeField}
          value={code}
          onChange={(v) => setCode(String(v ?? ""))}
        />
      );
    }
    render(
      <QueryClientProvider client={new QueryClient()}>
        <Controlled />
      </QueryClientProvider>,
    );
    const input = screen.getByRole("textbox", { name: "Product code" });

    fireEvent.change(input, { target: { value: "5" } });

    expect(screen.getByText(/gives an in-house code/)).toHaveClass("invisible");
    expect(input).not.toHaveAccessibleDescription();
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
