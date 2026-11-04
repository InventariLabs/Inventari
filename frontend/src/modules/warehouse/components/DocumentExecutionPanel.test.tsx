import { act } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@/test/utils";
import { DocumentExecutionPanel } from "./DocumentExecutionPanel";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import { documentLine } from "@/test/factories/documents";
import { warehouseDocument } from "@/test/factories/documents";

const scanCameraMock = vi.hoisted(() => {
  const state = {
    restartCamera: vi.fn(),
    toggleTorch: vi.fn(),
    triggerScan: (_code: string) => {},
  };

  return state;
});

vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: ({
    onCodeScanned,
  }: {
    onCodeScanned: (code: string) => void;
  }) => {
    scanCameraMock.triggerScan = onCodeScanned;

    return {
      scannerError: null,
      isCameraActive: true,
      setIsCameraActive: vi.fn(),
      isTorchOn: false,
      restartCamera: scanCameraMock.restartCamera,
      startCamera: vi.fn(),
      resumeCamera: vi.fn(),
      pauseCamera: vi.fn(),
      toggleTorch: scanCameraMock.toggleTorch,
    };
  },
}));

function buildDocument(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocument {
  return warehouseDocument({
    id: "doc-1",
    organization_id: "org-1",
    type: "IN",
    number: "PZ/2026/001",
    status: "CONFIRMED",
    partner_id: null,
    source_location_id: null,
    target_location_id: "loc-1",
    scheduled_date: null,
    notes: null,
    external_reference: null,
    lines: [
      documentLine({
        id: "line-1",
        document_id: "doc-1",
        item_id: "item-1",
        product_template_id: null,
        name: "Widget",
        brand: "ACME",
        barcode: "123456",
        quantity: "3",
        expected_quantity: "3",
        done_quantity: "0",
        batch_number: null,
        expiry_date: null,
        notes: null,
        line_number: 1,
      }),
    ],
    created_by: "user-1",
    confirmed_by: "user-1",
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-04-01T10:00:00Z",
    confirmed_at: "2026-04-01T11:00:00Z",
    completed_at: null,
    ...overrides,
  });
}

/** A dispatch whose one line came off the shelf in full. */
function pickedDispatch(): WarehouseDocument {
  const base = buildDocument();
  return buildDocument({
    type: "OUT",
    number: "WZ/2026/001",
    lines: [{ ...base.lines[0], done_quantity: "3" }],
  });
}

describe("DocumentExecutionPanel", () => {
  it("applies a scanned barcode to the matching line quantity", async () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Scan mode" }));
    fireEvent.change(screen.getByLabelText("Scan barcode"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply scan" }));

    expect(screen.getByLabelText("Executed quantity")).toHaveValue(1);
  });

  it("names the unit a line does not have instead of printing a bare number", () => {
    // A hand-typed line carries no unit. The sentence had a slot for one, and
    // the two things it put there — a dash, then nothing — both printed a
    // quantity dressed as a measurement the panel cannot back.
    const document = buildDocument();
    document.lines = [{ ...document.lines[0], uom: null, uom_id: null }];

    render(
      <DocumentExecutionPanel
        document={document}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(
      screen.getByText("Planned 3 · remaining 3 (no unit)"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Planned 3 - · remaining 3 -")).toBeNull();
    expect(screen.queryByText(/^Planned 3 · remaining 3$/)).toBeNull();
  });

  it("shows the quantity the wire's decimal padding means, not the padding", () => {
    // The quantity column serializes at its own scale, so ten pieces arrive
    // as "10.000". Handed to the field as it came, one reader takes the dot
    // for a decimal mark and another for a thousands separator — the same
    // digits read as ten thousand. The field shows the number itself.
    const document = buildDocument();
    document.lines = [
      {
        ...document.lines[0],
        quantity: "10.000",
        expected_quantity: "10.000",
        done_quantity: "10.000",
      },
    ];

    render(
      <DocumentExecutionPanel
        document={document}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const field = screen.getByLabelText(
      "Executed quantity",
    ) as HTMLInputElement;
    expect(field.value).toBe("10");
  });

  it("attaches the code-required error to the discrepancy field", async () => {
    const onSubmit = vi.fn();
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(screen.getByLabelText("Executed quantity"), {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm & complete" }));

    expect(onSubmit).not.toHaveBeenCalled();
    const select = screen.getByLabelText("Discrepancy code");
    expect(select.className).toContain("border-red-500");
    const card = screen.getByTestId("document-line-card-line-1");
    expect(
      within(card).getByText(/select a discrepancy code/i),
    ).toBeInTheDocument();
  });

  it("clears the field-level code error after selecting a code", async () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Executed quantity"), {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm & complete" }));
    const select = screen.getByLabelText("Discrepancy code");
    expect(select.className).toContain("border-red-500");

    fireEvent.change(select, { target: { value: "SHORTAGE" } });
    expect(select.className).not.toContain("border-red-500");
  });

  it("opens the camera flow in scan mode and applies camera scans", async () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Scan mode" }));
    fireEvent.click(screen.getByRole("button", { name: "Open camera" }));

    expect(scanCameraMock.restartCamera).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Aim at barcode or QR")).toBeInTheDocument();

    await act(async () => {
      scanCameraMock.triggerScan("123456");
    });

    expect(screen.getByLabelText("Executed quantity")).toHaveValue(1);
  });

  it("opens the camera when Apply scan is pressed on an empty field", () => {
    scanCameraMock.restartCamera.mockClear();
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Scan mode" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply scan" }));

    // Not a silent press: the camera the code can come from is open.
    expect(scanCameraMock.restartCamera).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Aim at barcode or QR")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Close camera" }),
    ).toBeInTheDocument();

    // Pressed again while it reads, it leaves the open camera alone.
    fireEvent.click(screen.getByRole("button", { name: "Apply scan" }));
    expect(scanCameraMock.restartCamera).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Aim at barcode or QR")).toBeInTheDocument();
  });

  it("shows live progress badges inside the sticky scan tray", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument({
          lines: [
            documentLine({
              id: "line-1",
              document_id: "doc-1",
              item_id: "item-1",
              product_template_id: null,
              name: "Widget",
              brand: "ACME",
              barcode: "123456",
              quantity: "1",
              expected_quantity: "1",
              done_quantity: "0",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 1,
            }),
            documentLine({
              id: "line-2",
              document_id: "doc-1",
              item_id: "item-2",
              product_template_id: null,
              name: "Cable",
              brand: "ACME",
              barcode: "999999",
              quantity: "2",
              expected_quantity: "2",
              done_quantity: "0",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 2,
            }),
          ],
        })}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Scan mode" }));

    expect(screen.getByText("Done: 0")).toBeInTheDocument();
    expect(screen.getByText("Pending: 2")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Scan barcode"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply scan" }));

    expect(screen.getByText("Done: 1")).toBeInTheDocument();
    expect(screen.getByText("Pending: 1")).toBeInTheDocument();
  });

  it("marks one active target line in scan mode and advances it after scanning", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument({
          lines: [
            documentLine({
              id: "line-1",
              document_id: "doc-1",
              item_id: "item-1",
              product_template_id: null,
              name: "Widget",
              brand: "ACME",
              barcode: "123456",
              quantity: "1",
              expected_quantity: "1",
              done_quantity: "0",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 1,
            }),
            documentLine({
              id: "line-2",
              document_id: "doc-1",
              item_id: "item-2",
              product_template_id: null,
              name: "Cable",
              brand: "ACME",
              barcode: "999999",
              quantity: "2",
              expected_quantity: "2",
              done_quantity: "0",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 2,
            }),
          ],
        })}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Scan mode" }));

    expect(screen.getByText("Up next")).toBeInTheDocument();
    expect(screen.getByTestId("document-line-card-line-1")).toHaveAttribute(
      "data-active-scan-target",
      "true",
    );
    expect(screen.getByTestId("document-line-card-line-2")).toHaveAttribute(
      "data-active-scan-target",
      "false",
    );

    fireEvent.change(screen.getByLabelText("Scan barcode"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply scan" }));

    expect(screen.getByTestId("document-line-card-line-1")).toHaveAttribute(
      "data-active-scan-target",
      "false",
    );
    expect(screen.getByTestId("document-line-card-line-2")).toHaveAttribute(
      "data-active-scan-target",
      "true",
    );
  });

  it("supports quick increment and caps at the planned quantity", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const incrementButton = screen.getByRole("button", { name: "+1" });

    fireEvent.click(incrementButton);
    fireEvent.click(incrementButton);
    fireEvent.click(incrementButton);
    fireEvent.click(incrementButton);

    expect(screen.getByLabelText("Executed quantity")).toHaveValue(3);
  });

  it("supports fill remaining and clear actions", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByLabelText("Executed quantity")).toHaveValue(0);

    fireEvent.click(screen.getByRole("button", { name: "Fill remaining" }));
    expect(screen.getByLabelText("Executed quantity")).toHaveValue(3);
  });

  it("opens a line nobody has executed yet without calling its own zero invalid", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    // Nothing received yet is the resting state of every confirmed document,
    // not a value someone typed wrong: the field is allowed to sit at zero
    // even though the unit refuses a quantity that small anywhere else.
    const field = screen.getByLabelText("Executed quantity");

    expect(field).toHaveValue(0);
    expect(field).not.toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/Must be at least/)).not.toBeInTheDocument();
  });

  it("keeps the zero legal after Clear asks for it", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    const field = screen.getByLabelText("Executed quantity");

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(field).toHaveValue(0);
    expect(field).not.toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText(/Must be at least/)).not.toBeInTheDocument();
  });

  it("keeps discrepancy note collapsed until requested", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    expect(screen.getByLabelText("Discrepancy code")).toBeInTheDocument();
    expect(
      screen.queryByLabelText("Discrepancy reason"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add note" }));

    expect(screen.getByLabelText("Discrepancy reason")).toBeInTheDocument();
  });

  it("opens discrepancy note automatically when the line already has one", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument({
          lines: [
            documentLine({
              id: "line-1",
              document_id: "doc-1",
              item_id: "item-1",
              product_template_id: null,
              name: "Widget",
              brand: "ACME",
              barcode: "123456",
              quantity: "3",
              expected_quantity: "3",
              done_quantity: "1",
              discrepancy_code: "DAMAGE",
              discrepancy_reason: "Outer box torn",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 1,
            }),
          ],
        })}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Discrepancy reason")).toHaveValue(
      "Outer box torn",
    );
  });

  it("guides the operator to the next incomplete line after a scan", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument({
          lines: [
            documentLine({
              id: "line-1",
              document_id: "doc-1",
              item_id: "item-1",
              product_template_id: null,
              name: "Widget",
              brand: "ACME",
              barcode: "123456",
              quantity: "1",
              expected_quantity: "1",
              done_quantity: "0",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 1,
            }),
            documentLine({
              id: "line-2",
              document_id: "doc-1",
              item_id: "item-2",
              product_template_id: null,
              name: "Cable",
              brand: "ACME",
              barcode: "999999",
              quantity: "2",
              expected_quantity: "2",
              done_quantity: "0",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 2,
            }),
          ],
        })}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Scan mode" }));
    fireEvent.change(screen.getByLabelText("Scan barcode"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply scan" }));

    expect(screen.getByText("Next Line: Cable")).toBeInTheDocument();
    expect(screen.getByText("Recently scanned")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Executed quantity", {
        selector: "input#done-quantity-line-2",
      }),
    ).toHaveFocus();
  });

  it("shows line number and execution status in each execution card", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText("Line #1")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("completes a dispatch with the carrier and tracking number typed", async () => {
    const onSubmit = vi.fn();
    render(
      <DocumentExecutionPanel
        document={pickedDispatch()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    fireEvent.change(await screen.findByLabelText("Carrier"), {
      target: { value: "UPS" },
    });
    fireEvent.change(screen.getByLabelText("Tracking number"), {
      target: { value: "1Z999" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm & complete" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        lines: [expect.objectContaining({ line_id: "line-1" })],
        shipment: { carrier: "UPS", tracking_number: "1Z999" },
      }),
    );
  });

  it("completes a dispatch without a shipment when both fields stay empty", async () => {
    const onSubmit = vi.fn();
    render(
      <DocumentExecutionPanel
        document={pickedDispatch()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={onSubmit}
      />,
    );

    await screen.findByLabelText("Carrier");
    fireEvent.click(screen.getByRole("button", { name: "Confirm & complete" }));

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty("shipment");
  });

  it("offers no carrier on a receipt", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.queryByLabelText("Carrier")).not.toBeInTheDocument();
  });

  it("keeps execution actions sticky on mobile", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByTestId("document-execution-actions")).toHaveClass(
      "sticky",
      "bottom-20",
    );
    expect(
      screen.getByRole("button", { name: "Confirm & complete" }),
    ).toBeInTheDocument();
  });

  it("lets the actions bar stop floating while the camera is open on a phone", () => {
    // Floating over the panel, the bar sat on the lower half of the camera
    // picture and on the sentence a refused camera shows — a scan screen
    // whose camera the worker could not see. With the camera open the bar
    // waits at the end of the panel; closed, it floats again.
    render(
      <DocumentExecutionPanel
        document={buildDocument()}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );
    const actions = screen.getByTestId("document-execution-actions");

    fireEvent.click(screen.getByRole("button", { name: "Scan mode" }));
    fireEvent.click(screen.getByRole("button", { name: "Open camera" }));
    expect(actions).not.toHaveClass("sticky");

    fireEvent.click(screen.getByRole("button", { name: "Close camera" }));
    expect(actions).toHaveClass("sticky", "bottom-20");
  });

  it("moves focus to the next incomplete line after fill remaining", () => {
    render(
      <DocumentExecutionPanel
        document={buildDocument({
          lines: [
            documentLine({
              id: "line-1",
              document_id: "doc-1",
              item_id: "item-1",
              product_template_id: null,
              name: "Widget",
              brand: "ACME",
              barcode: "123456",
              quantity: "1",
              expected_quantity: "1",
              done_quantity: "0",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 1,
            }),
            documentLine({
              id: "line-2",
              document_id: "doc-1",
              item_id: "item-2",
              product_template_id: null,
              name: "Cable",
              brand: "ACME",
              barcode: "999999",
              quantity: "2",
              expected_quantity: "2",
              done_quantity: "0",
              batch_number: null,
              expiry_date: null,
              notes: null,
              line_number: 2,
            }),
          ],
        })}
        isPending={false}
        onCancel={vi.fn()}
        onSubmit={vi.fn()}
      />,
    );

    fireEvent.click(
      screen.getAllByRole("button", { name: "Fill remaining" })[0],
    );

    expect(
      screen.getByLabelText("Executed quantity", {
        selector: "input#done-quantity-line-2",
      }),
    ).toHaveFocus();
  });
});
