import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen } from "@/test/utils";
import { DocumentFormatSettings } from "./DocumentFormatSettings";

const baseProps = {
  numberingFormat: "{TYPE}/{YEAR}/{SEQ:03d}",
  numberPadding: 3,
  typeLabelIN: "PZ",
  typeLabelOUT: "WZ",
  typeLabelINT: "MM",
  typeLabelInternalIn: "PW",
  typeLabelInternalOut: "RW",
  typeLabelCORR: "KOR",
  typeLabelSCRAP: "ZL",
  typeLabelADJ: "",
  onNumberingFormatChange: vi.fn(),
  onNumberPaddingChange: vi.fn(),
  onTypeLabelINChange: vi.fn(),
  onTypeLabelOUTChange: vi.fn(),
  onTypeLabelINTChange: vi.fn(),
  onTypeLabelInternalInChange: vi.fn(),
  onTypeLabelInternalOutChange: vi.fn(),
  onTypeLabelCORRChange: vi.fn(),
  onTypeLabelSCRAPChange: vi.fn(),
  onTypeLabelADJChange: vi.fn(),
};

describe("DocumentFormatSettings — number padding", () => {
  function getPaddingSelect(): HTMLSelectElement {
    const labels = screen.getAllByText("Number Padding");
    expect(labels.length).toBeGreaterThan(0);
    const wrapper = labels[0].closest("div");
    const select = wrapper?.parentElement?.querySelector("select");
    if (!select) throw new Error("padding select not found");
    return select as HTMLSelectElement;
  }

  function getNumberingInput(
    value: string = "{TYPE}/{YEAR}/{SEQ:03d}",
  ): HTMLInputElement {
    return screen.getByDisplayValue(value) as HTMLInputElement;
  }

  it("renders the number padding select with the current value", () => {
    render(<DocumentFormatSettings {...baseProps} numberPadding={4} />);

    const select = getPaddingSelect();
    expect(select.value).toBe("4");
  });

  it("suggests type labels in the reading language, not one country's codes", () => {
    render(<DocumentFormatSettings {...baseProps} />);

    expect(screen.getByPlaceholderText("Receipt")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Delivery")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Transfer")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Internal Receipt")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Internal Issue")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Correction")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Scrap")).toBeInTheDocument();
  });

  it("lets scrap documents be named like every other type", async () => {
    const onTypeLabelSCRAPChange = vi.fn();
    const user = userEvent.setup();

    render(
      <DocumentFormatSettings
        {...baseProps}
        typeLabelSCRAP=""
        onTypeLabelSCRAPChange={onTypeLabelSCRAPChange}
      />,
    );

    await user.type(screen.getByPlaceholderText("Scrap"), "Z");

    expect(onTypeLabelSCRAPChange).toHaveBeenCalledWith("Z");
  });

  it("lets stock adjustments be named too", async () => {
    const onTypeLabelADJChange = vi.fn();
    const user = userEvent.setup();

    render(
      <DocumentFormatSettings
        {...baseProps}
        onTypeLabelADJChange={onTypeLabelADJChange}
      />,
    );

    await user.type(screen.getByLabelText("Label for Adjustment"), "A");

    expect(onTypeLabelADJChange).toHaveBeenCalledWith("A");
  });

  it("offers 3..6 digit options", () => {
    render(<DocumentFormatSettings {...baseProps} />);

    const select = getPaddingSelect();
    const optionValues = Array.from(select.querySelectorAll("option")).map(
      (o) => o.value,
    );
    expect(optionValues).toEqual(["3", "4", "5", "6"]);
  });

  it("changing padding rewrites the {SEQ:Nd} token in numbering_format", async () => {
    const onNumberPaddingChange = vi.fn();
    const onNumberingFormatChange = vi.fn();
    const user = userEvent.setup();

    render(
      <DocumentFormatSettings
        {...baseProps}
        numberingFormat="{TYPE}/{YEAR}/{SEQ:03d}"
        numberPadding={3}
        onNumberingFormatChange={onNumberingFormatChange}
        onNumberPaddingChange={onNumberPaddingChange}
      />,
    );

    const select = getPaddingSelect();
    await user.selectOptions(select, "5");

    expect(onNumberPaddingChange).toHaveBeenCalledWith(5);
    expect(onNumberingFormatChange).toHaveBeenCalledWith(
      "{TYPE}/{YEAR}/{SEQ:05d}",
    );
  });

  it("changing numbering_format with a new token width updates padding", async () => {
    const onNumberPaddingChange = vi.fn();
    const onNumberingFormatChange = vi.fn();

    render(
      <DocumentFormatSettings
        {...baseProps}
        numberingFormat="{TYPE}/{YEAR}/{SEQ:03d}"
        numberPadding={3}
        onNumberingFormatChange={onNumberingFormatChange}
        onNumberPaddingChange={onNumberPaddingChange}
      />,
    );

    const input = getNumberingInput();
    fireEvent.change(input, { target: { value: "{TYPE}/{YEAR}/{SEQ:06d}" } });

    expect(onNumberingFormatChange).toHaveBeenCalled();
    expect(onNumberPaddingChange).toHaveBeenCalledWith(6);
  });

  it("changing numbering_format without {SEQ:Nd} keeps padding unchanged", async () => {
    const onNumberPaddingChange = vi.fn();
    const onNumberingFormatChange = vi.fn();

    render(
      <DocumentFormatSettings
        {...baseProps}
        numberingFormat="{TYPE}/{YEAR}/{SEQ:04d}"
        numberPadding={4}
        onNumberingFormatChange={onNumberingFormatChange}
        onNumberPaddingChange={onNumberPaddingChange}
      />,
    );

    const input = getNumberingInput("{TYPE}/{YEAR}/{SEQ:04d}");
    fireEvent.change(input, { target: { value: "{TYPE}/{YEAR}/" } });

    expect(onNumberingFormatChange).toHaveBeenCalled();
    expect(onNumberPaddingChange).not.toHaveBeenCalled();
  });
});

describe("DocumentFormatSettings — the example under the format", () => {
  // The hint used to print the receipt's label in this language followed by
  // "/2026/001" whatever the format said: "Receipt/2026/001" for a profile
  // that names no label (the engine writes the short code, IN) and for one
  // numbering PZ/<year>/<month>/<four digits>.
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");

  it("writes the short code when the profile names no receipt label", () => {
    render(
      <DocumentFormatSettings
        {...baseProps}
        numberingFormat="{TYPE_LABEL}/{YEAR}/{SEQ:03d}"
        typeLabelIN=""
      />,
    );

    expect(screen.getByText(new RegExp(`IN/${year}/001`))).toBeInTheDocument();
  });

  it("follows the month and the padding the format carries", () => {
    render(
      <DocumentFormatSettings
        {...baseProps}
        numberingFormat="{TYPE_LABEL}/{YEAR}/{MONTH}/{SEQ:04d}"
        numberPadding={4}
        typeLabelIN="PZ"
      />,
    );

    expect(
      screen.getByText(new RegExp(`PZ/${year}/${month}/0001`)),
    ).toBeInTheDocument();
  });
});
