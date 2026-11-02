import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, within } from "@/test/utils";

import DocumentDetailModals from "./DocumentDetailModals";
import type { WarehouseDocument } from "@/modules/warehouse/types";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigate,
}));

/** The picking sheet at its summary: the two ways out it hands the page. */
vi.mock("@/modules/warehouse/components/picking/WmsPickingView", () => ({
  default: ({
    onClose,
    onPack,
  }: {
    onClose: (completed?: boolean) => void;
    onPack?: () => void;
  }) => (
    <div>
      <button onClick={() => onClose(true)}>Close</button>
      {onPack && <button onClick={onPack}>Pack</button>}
    </div>
  ),
}));

const closed = {
  editOpen: false,
  onEditClose: vi.fn(),
  correctionOpen: false,
  onCorrectionClose: vi.fn(),
  returnOpen: false,
  onReturnClose: vi.fn(),
  pickingOpen: false,
  onPickingClose: vi.fn(),
  receivingOpen: false,
  onReceivingClose: vi.fn(),
  confirmTitle: "Cancel this document?",
  confirmMessage: "This cannot be undone.",
  confirmVariant: "danger" as const,
  onConfirmAction: vi.fn(),
  onConfirmCancel: vi.fn(),
};

const doc = { id: "d-1", type: "IN", status: "DRAFT" } as WarehouseDocument;

describe("DocumentDetailModals confirm dialog", () => {
  it("words the two cancel-document buttons as different decisions", () => {
    render(
      <DocumentDetailModals doc={doc} confirmAction="cancel" {...closed} />,
    );

    expect(
      screen.getByRole("button", { name: "Cancel document" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Keep document" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();
  });

  it("names the delete and the keep of a draft", () => {
    render(
      <DocumentDetailModals doc={doc} confirmAction="delete" {...closed} />,
    );

    expect(
      screen.getByRole("button", { name: "Delete draft" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Keep draft" }),
    ).toBeInTheDocument();
  });

  it("names the one-step action as sending for approval when that is all it does", () => {
    render(
      <DocumentDetailModals
        doc={doc}
        confirmAction="postNow"
        {...closed}
        postNowSendsForApproval
      />,
    );

    expect(
      screen.getByRole("button", { name: "Send for approval" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Post" }),
    ).not.toBeInTheDocument();
  });

  it("keeps Post on the one-step action that posts", () => {
    render(
      <DocumentDetailModals doc={doc} confirmAction="postNow" {...closed} />,
    );

    expect(screen.getByRole("button", { name: "Post" })).toBeInTheDocument();
  });

  it("leaves the plain Confirm and Cancel on a confirmation", () => {
    render(
      <DocumentDetailModals doc={doc} confirmAction="confirm" {...closed} />,
    );

    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });
});

describe("DocumentDetailModals picking summary", () => {
  it("offers packing on a dispatch: closes without completing and points at the step", async () => {
    const onPickingClose = vi.fn();
    const dispatch = {
      id: "d-2",
      type: "OUT",
      status: "CONFIRMED",
    } as WarehouseDocument;
    render(
      <DocumentDetailModals
        doc={dispatch}
        confirmAction={null}
        {...closed}
        pickingOpen
        onPickingClose={onPickingClose}
      />,
    );

    await userEvent.click(await screen.findByRole("button", { name: "Pack" }));

    expect(onPickingClose).toHaveBeenCalledWith(false);
    expect(navigate).toHaveBeenCalledWith("#pack", { replace: true });
  });

  it("offers no packing on a transfer", async () => {
    const transfer = {
      id: "d-3",
      type: "INT",
      status: "CONFIRMED",
    } as WarehouseDocument;
    render(
      <DocumentDetailModals
        doc={transfer}
        confirmAction={null}
        {...closed}
        pickingOpen
      />,
    );

    await screen.findByRole("button", { name: "Close" });
    expect(screen.queryByRole("button", { name: "Pack" })).toBeNull();
  });
});

describe("DocumentDetailModals receipt expiry question", () => {
  it("reads the lot and date of the undated line and hands them back", async () => {
    const onConfirm = vi.fn();
    render(
      <DocumentDetailModals
        doc={doc}
        confirmAction={null}
        {...closed}
        receiptExpiry={{
          prompt: { lineId: "l1", product: "Yoghurt" },
          onConfirm,
          onClose: vi.fn(),
        }}
      />,
    );

    const dialog = await screen.findByRole("dialog", {
      name: "Lot and expiry",
    });
    expect(within(dialog).getByText(/Yoghurt/)).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Lot"), "LOT-C1");
    await userEvent.click(within(dialog).getByRole("combobox"));
    await userEvent.click(
      within(screen.getAllByRole("dialog").at(-1)!).getAllByTestId(
        "date-preset",
      )[1],
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Receive" }),
    );

    expect(onConfirm).toHaveBeenCalledWith(
      "LOT-C1",
      expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    );
  });

  it("starts the sheet blank for the next line, even when it is the same product", async () => {
    const onConfirm = vi.fn();
    const { rerender } = render(
      <DocumentDetailModals
        doc={doc}
        confirmAction={null}
        {...closed}
        receiptExpiry={{
          prompt: { lineId: "l1", product: "Yoghurt" },
          onConfirm,
          onClose: vi.fn(),
        }}
      />,
    );

    const first = await screen.findByRole("dialog", { name: "Lot and expiry" });
    await userEvent.type(within(first).getByLabelText("Lot"), "LOT-ALPHA");

    rerender(
      <DocumentDetailModals
        doc={doc}
        confirmAction={null}
        {...closed}
        receiptExpiry={{
          prompt: { lineId: "l2", product: "Yoghurt" },
          onConfirm,
          onClose: vi.fn(),
        }}
      />,
    );

    const second = screen.getByRole("dialog", { name: "Lot and expiry" });
    expect(within(second).getByLabelText("Lot")).toHaveValue("");
  });
});
