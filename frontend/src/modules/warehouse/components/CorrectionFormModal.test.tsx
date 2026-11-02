import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { CorrectionFormModal } from "./CorrectionFormModal";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { documentLine } from "@/test/factories/documents";
import { warehouseDocument } from "@/test/factories/documents";

const { mutateMock } = vi.hoisted(() => ({
  mutateMock: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", () => ({
  useCreateCorrection: () => ({
    mutate: mutateMock,
    isPending: false,
  }),
}));

function makeDocument(
  overrides?: Partial<WarehouseDocument>,
): WarehouseDocument {
  return warehouseDocument({
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "IN/2026/001",
    status: "COMPLETED",
    partner_id: null,
    source_location_id: null,
    target_location_id: null,
    scheduled_date: null,
    notes: null,
    external_reference: null,
    lines: [
      documentLine({
        id: "line-1",
        document_id: "doc-1",
        line_number: 1,
        name: "Widget",
        quantity: "3",
        done_quantity: "3",
        expiry_date: null,
        notes: null,
        item_id: null,
        product_template_id: null,
        brand: null,
        barcode: null,
        sku: null,
        uom_id: null,
        batch_number: null,
        serial_number: null,
        unit_price: null,
        tax_rate: null,
      }),
    ],
    created_by: "user-1",
    confirmed_by: null,
    confirmed_at: null,
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
    completed_at: "2026-01-02T00:00:00",
    ...overrides,
  });
}

describe("CorrectionFormModal", () => {
  it("clamps a negative delta to the executed quantity", async () => {
    render(<CorrectionFormModal document={makeDocument()} onClose={vi.fn()} />);

    expect(screen.getByText("Executed: 3")).toBeInTheDocument();

    const deltaInput = screen.getByRole("spinbutton", { name: "Change" });
    fireEvent.change(deltaInput, { target: { value: "-15" } });

    // The reader's text stays until they leave the field — a rewrite
    // mid-typing is what used to eat the dot of a fraction. The
    // bound is said meanwhile, and lands on blur.
    expect((deltaInput as HTMLInputElement).value).toBe("-15");
    // the label describes the lower bound, not a maximum.
    expect(screen.getByText("You can remove up to 3")).toBeInTheDocument();

    fireEvent.blur(deltaInput);
    expect((deltaInput as HTMLInputElement).value).toBe("-3");
  });

  it("treats a cleared field as no change, not as NaN", async () => {
    // Number("") is NaN; it survived the clamp, counted as a changed line and
    // was posted as null, which the API answered with a 422. A cleared field
    // still means a delta of zero — it says so on blur instead of rewriting
    // the empty into the field mid-typing.
    const user = userEvent.setup();
    render(<CorrectionFormModal document={makeDocument()} onClose={vi.fn()} />);

    const deltaInput = screen.getByRole("spinbutton", { name: "Change" });
    fireEvent.change(deltaInput, { target: { value: "-2" } });
    fireEvent.change(deltaInput, { target: { value: "" } });

    expect((deltaInput as HTMLInputElement).value).toBe("");
    fireEvent.blur(deltaInput);
    expect((deltaInput as HTMLInputElement).value).toBe("0");
    await user.selectOptions(
      screen.getByTestId("correction-reason-code"),
      "WRONG_QUANTITY",
    );
    expect(
      screen.getByRole("button", { name: /create correction/i }),
    ).toBeDisabled();
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it("does not clamp a positive delta", async () => {
    render(<CorrectionFormModal document={makeDocument()} onClose={vi.fn()} />);

    const deltaInput = screen.getByRole("spinbutton", { name: "Change" });
    fireEvent.change(deltaInput, { target: { value: "15" } });

    // Only the lower side is bounded — over-receipt corrections are allowed.
    expect((deltaInput as HTMLInputElement).value).toBe("15");
  });

  it("blocks 'Other' with a whitespace-only note", async () => {
    const user = userEvent.setup();
    render(<CorrectionFormModal document={makeDocument()} onClose={vi.fn()} />);

    const deltaInput = screen.getByRole("spinbutton", { name: "Change" });
    fireEvent.change(deltaInput, { target: { value: "-1" } });

    await user.selectOptions(
      screen.getByTestId("correction-reason-code"),
      "OTHER",
    );
    await user.type(screen.getByTestId("correction-reason-note"), "   ");
    await user.click(
      screen.getByRole("button", { name: "Create Correction (1 line)" }),
    );

    expect(mutateMock).not.toHaveBeenCalled();
    expect(
      screen.getByText("Say what happened, or pick a named reason"),
    ).toBeInTheDocument();
  });

  it("says the reason is missing instead of leaving the button dead", async () => {
    const user = userEvent.setup();
    render(<CorrectionFormModal document={makeDocument()} onClose={vi.fn()} />);

    const deltaInput = screen.getByRole("spinbutton", { name: "Change" });
    fireEvent.change(deltaInput, { target: { value: "-1" } });

    // The button counts lines, so a disabled one reads as "not enough lines".
    const submit = screen.getByRole("button", {
      name: "Create Correction (1 line)",
    });
    expect(submit).toBeEnabled();

    await user.click(submit);

    expect(mutateMock).not.toHaveBeenCalled();
    expect(screen.getByText("Pick a reason")).toBeInTheDocument();
  });

  it("does not ask for a note under a named reason", async () => {
    const user = userEvent.setup();
    render(<CorrectionFormModal document={makeDocument()} onClose={vi.fn()} />);

    fireEvent.change(screen.getByRole("spinbutton", { name: "Change" }), {
      target: { value: "-1" },
    });
    await user.selectOptions(
      screen.getByTestId("correction-reason-code"),
      "WRONG_PRICE",
    );
    await user.click(
      screen.getByRole("button", { name: "Create Correction (1 line)" }),
    );

    expect(mutateMock).toHaveBeenCalledWith(
      expect.objectContaining({ reason_code: "WRONG_PRICE", notes: null }),
      expect.any(Object),
    );
  });

  it("submits the clamped delta with the reason", async () => {
    const user = userEvent.setup();
    render(<CorrectionFormModal document={makeDocument()} onClose={vi.fn()} />);

    const deltaInput = screen.getByRole("spinbutton", { name: "Change" });
    fireEvent.change(deltaInput, { target: { value: "-15" } });

    await user.selectOptions(
      screen.getByTestId("correction-reason-code"),
      "OTHER",
    );
    await user.type(
      screen.getByTestId("correction-reason-note"),
      "Damage found during cycle count",
    );

    await user.click(
      screen.getByRole("button", { name: "Create Correction (1 line)" }),
    );

    expect(mutateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        corrects_document_id: "doc-1",
        lines: [
          expect.objectContaining({
            original_line_number: 1,
            quantity_delta: -3,
          }),
        ],
        reason_code: "OTHER",
        notes: "Damage found during cycle count",
      }),
      expect.any(Object),
    );
  });

  describe("leaving a filled-in sheet", () => {
    it("asks before Escape throws away an entered quantity", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(
        <CorrectionFormModal document={makeDocument()} onClose={onClose} />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      await user.keyboard("{Escape}");

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before the close button discards it", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(
        <CorrectionFormModal document={makeDocument()} onClose={onClose} />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      await user.click(screen.getByRole("button", { name: "Close" }));

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before a click on the backdrop discards it", async () => {
      const onClose = vi.fn();
      render(
        <CorrectionFormModal document={makeDocument()} onClose={onClose} />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;
      fireEvent.mouseDown(backdrop);
      fireEvent.click(backdrop);

      expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("asks before the cancel button discards it, and closes on confirm", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(
        <CorrectionFormModal document={makeDocument()} onClose={onClose} />,
      );
      fireEvent.change(screen.getByRole("spinbutton"), {
        target: { value: "1" },
      });

      await user.click(screen.getByRole("button", { name: "Cancel" }));
      expect(onClose).not.toHaveBeenCalled();

      await user.click(await screen.findByRole("button", { name: "Discard" }));
      expect(onClose).toHaveBeenCalledOnce();
    });

    it("closes an untouched sheet without a question", async () => {
      const onClose = vi.fn();
      const user = userEvent.setup();
      render(
        <CorrectionFormModal document={makeDocument()} onClose={onClose} />,
      );

      await user.keyboard("{Escape}");

      expect(onClose).toHaveBeenCalledOnce();
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    });
  });
});
