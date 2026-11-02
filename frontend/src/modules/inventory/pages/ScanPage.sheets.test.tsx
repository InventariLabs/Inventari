import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { signInWith, signOut } from "@/test/auth";
import { labelsApi } from "@/lib/api/labels";
import { useScanStore } from "@/store/scanStore";
import type { LabelScanView } from "@/types";
import ScanPage from "./ScanPage";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  camera: {
    onCodeScanned: null as ((code: string) => void) | null,
    pauseCamera: vi.fn(() => Promise.resolve()),
    resumeCamera: vi.fn(),
    restartCamera: vi.fn(),
    toggleTorch: vi.fn(),
    setIsCameraActive: vi.fn(),
  },
  addToShoppingList: vi.fn(),
  consume: vi.fn(),
  updateQuantity: vi.fn(),
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mocks.navigate };
});

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/api/labels", () => ({
  labelsApi: { scan: vi.fn() },
}));

vi.mock("@/hooks/useScanCamera", () => ({
  useScanCamera: ({
    onCodeScanned,
  }: {
    onCodeScanned: (c: string) => void;
  }) => {
    mocks.camera.onCodeScanned = onCodeScanned;
    return {
      scannerError: null,
      isCameraActive: true,
      isTorchOn: false,
      setIsCameraActive: mocks.camera.setIsCameraActive,
      restartCamera: mocks.camera.restartCamera,
      resumeCamera: mocks.camera.resumeCamera,
      pauseCamera: mocks.camera.pauseCamera,
      toggleTorch: mocks.camera.toggleTorch,
    };
  },
}));

vi.mock("@/module-sdk", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/module-sdk")>();
  return { ...actual, useLocationOffer: () => ({ total: 2 }) };
});

vi.mock("@/modules/inventory/hooks/useScanActions", () => ({
  useScanConsume: () => ({ mutateAsync: mocks.consume }),
  useScanUsePartially: () => vi.fn(),
  useScanUpdateQuantity: () => ({ mutateAsync: mocks.updateQuantity }),
  useScanAddToShoppingList: () => ({
    mutateAsync: mocks.addToShoppingList,
  }),
}));

// The sheets are the page's children with tests of their own; here they are
// the buttons the page wires up, so what the page does with each answer shows.
vi.mock("../components/ScanCameraView", () => ({
  default: (props: {
    onBack: () => void;
    onStartCamera: () => void;
    onRestartCamera: () => void;
    onToggleTorch: () => void;
    onClearStorageContext: () => void;
    onManualCode: (code: string) => void;
    lookupFailure?: { code: string; message: string } | null;
    onDismissLookupFailure: () => void;
  }) => (
    <div>
      {props.lookupFailure && (
        <div role="alert">
          {props.lookupFailure.code}: {props.lookupFailure.message}
          <button onClick={props.onDismissLookupFailure}>dismiss</button>
        </div>
      )}
      <button onClick={props.onBack}>back</button>
      <button onClick={props.onStartCamera}>start camera</button>
      <button onClick={props.onClearStorageContext}>clear context</button>
      <button onClick={() => props.onManualCode("LBL-1")}>type code</button>
    </div>
  ),
}));

vi.mock("@/modules/inventory/components/QuickAddModal", () => ({
  default: (props: {
    labelCode: string;
    onClose: () => void;
    onSuccess: () => void;
  }) => (
    <div role="dialog" aria-label="quick add">
      <span>label {props.labelCode}</span>
      <button onClick={props.onClose}>close quick add</button>
      <button onClick={props.onSuccess}>save quick add</button>
    </div>
  ),
}));

vi.mock("@/modules/inventory/components/QuickActionSheet", () => ({
  default: (props: { onClose: () => void; onViewDetails: () => void }) => (
    <div role="dialog" aria-label="quick actions">
      <button onClick={props.onClose}>close actions</button>
      <button onClick={props.onViewDetails}>details</button>
    </div>
  ),
}));

vi.mock("../components/ItemEditModal", () => ({
  default: (props: { itemId: string; onClose: () => void }) => (
    <div role="dialog" aria-label="edit">
      <span>editing {props.itemId}</span>
      <button onClick={props.onClose}>close edit</button>
    </div>
  ),
}));

vi.mock("../components/ArchivedItemSheet", () => ({
  default: (props: { onClose: () => void; onReuse: () => void }) => (
    <div role="dialog" aria-label="archived">
      <button onClick={props.onClose}>close archived</button>
      <button onClick={props.onReuse}>reuse label</button>
    </div>
  ),
}));

vi.mock("../components/StockActionSheet", () => ({
  default: (props: {
    onClose: () => void;
    onAdd: () => void;
    onAddOne: (id: string) => void;
    onConsume: (id?: string) => void;
    onAddToShoppingList?: () => void;
  }) => (
    <div role="dialog" aria-label="stock">
      <button onClick={props.onClose}>close stock</button>
      <button onClick={props.onAdd}>add more</button>
      <button onClick={() => props.onAddOne("missing")}>add one missing</button>
      <button onClick={() => props.onConsume("item-1")}>consume one</button>
      {props.onAddToShoppingList && (
        <button onClick={props.onAddToShoppingList}>to shopping list</button>
      )}
    </div>
  ),
}));

const item = { id: "item-1", name: "Rice", quantity: 2 };

function scanAnswers(view: Partial<LabelScanView>) {
  vi.mocked(labelsApi.scan).mockResolvedValue({
    label_code: "LBL-1",
    ...view,
  } as unknown as LabelScanView);
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ScanPage />
    </MemoryRouter>,
  );
}

/**
 * Which sheet a scanned label opens, and what closing each sheet does: every
 * way out hands the camera back, "details" swaps the actions for the edit
 * form on the scanned record, an archived label can be reused for a new
 * record, and the stock sheet's add and shopping-list actions leave it. A
 * way out that forgets `resumeCamera` leaves the reader in front of a frozen
 * viewfinder.
 */
describe("ScanPage — the sheets a scan opens, and the ways out of them", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["items:read", "items:write", "shopping_lists:write"]);
    useScanStore.getState().setStorageContext(null);
  });

  afterEach(() => signOut());

  it("opens the quick actions for a scanned record, then its edit form", async () => {
    scanAnswers({ action: "show_quick_actions", item } as never);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    expect(mocks.camera.pauseCamera).toHaveBeenCalled();
    await user.click(await screen.findByRole("button", { name: "details" }));

    expect(screen.getByText("editing item-1")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "quick actions" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "close edit" }));
    expect(screen.queryByRole("dialog", { name: "edit" })).toBeNull();
    expect(mocks.camera.resumeCamera).toHaveBeenCalledTimes(1);
  });

  it("hands the camera back when the quick actions close", async () => {
    scanAnswers({ action: "show_quick_actions", item } as never);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    await user.click(
      await screen.findByRole("button", { name: "close actions" }),
    );
    expect(mocks.camera.resumeCamera).toHaveBeenCalledTimes(1);
  });

  it("keeps the refusal of a typed code on the page instead of a toast, until the next code or a dismiss", async () => {
    vi.mocked(labelsApi.scan).mockRejectedValueOnce(
      new AxiosError("refused", "404", undefined, undefined, {
        status: 404,
        statusText: "",
        data: {
          detail: { code: "SCAN_UNRECOGNIZED", message: "Nothing matches" },
        },
        headers: {},
        config: {} as never,
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("LBL-1");
    expect(toast.error).not.toHaveBeenCalled();
    expect(mocks.camera.resumeCamera).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "dismiss" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reuses an archived label for a new record, and closes back to the camera", async () => {
    scanAnswers({ action: "show_archived_info", item } as never);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    await user.click(
      await screen.findByRole("button", { name: "reuse label" }),
    );
    expect(screen.getByText("label LBL-1")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "save quick add" }));
    expect(screen.queryByRole("dialog", { name: "quick add" })).toBeNull();
    expect(mocks.camera.resumeCamera).toHaveBeenCalledTimes(1);
  });

  it("closes an archived label's sheet back to the camera", async () => {
    scanAnswers({ action: "show_archived_info", item } as never);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    await user.click(
      await screen.findByRole("button", { name: "close archived" }),
    );
    expect(mocks.camera.resumeCamera).toHaveBeenCalledTimes(1);
  });

  it("takes a blank label into the form, and a second scan only renames the label", async () => {
    scanAnswers({ action: "show_quick_add" } as never);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    expect(await screen.findByText("label LBL-1")).toBeInTheDocument();

    // Batch mode: the camera keeps reading while the form is open.
    await act(async () => mocks.camera.onCodeScanned?.("LBL-2"));
    expect(screen.getByText("label LBL-2")).toBeInTheDocument();
    expect(labelsApi.scan).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "close quick add" }));
    expect(mocks.camera.resumeCamera).toHaveBeenCalledTimes(1);
  });

  const stockView = {
    action: "show_stock_actions",
    stock_summary: {
      template: { name: "Rice" },
      items: [{ id: "item-1", quantity: 2, expiry_date: null }],
    },
  } as never;

  it("leaves the stock sheet for the form when more is added", async () => {
    scanAnswers(stockView);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    await user.click(await screen.findByRole("button", { name: "add more" }));
    expect(screen.queryByRole("dialog", { name: "stock" })).toBeNull();
    expect(
      screen.getByRole("dialog", { name: "quick add" }),
    ).toBeInTheDocument();
  });

  it("puts the scanned product on the shopping list and leaves the sheet", async () => {
    scanAnswers(stockView);
    mocks.addToShoppingList.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    await user.click(
      await screen.findByRole("button", { name: "to shopping list" }),
    );

    expect(mocks.addToShoppingList).toHaveBeenCalledWith({
      templateName: "Rice",
    });
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "stock" })).toBeNull(),
    );
    expect(mocks.camera.resumeCamera).toHaveBeenCalledTimes(1);
  });

  it("keeps the stock sheet and says so when the shopping list refuses", async () => {
    scanAnswers(stockView);
    mocks.addToShoppingList.mockRejectedValue(new Error("x"));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    await user.click(
      await screen.findByRole("button", { name: "to shopping list" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Could not add to shopping list",
      ),
    );
    expect(screen.getByRole("dialog", { name: "stock" })).toBeInTheDocument();
  });

  it("reports a refused consume and adds nothing for a record not on the label", async () => {
    scanAnswers(stockView);
    mocks.consume.mockRejectedValue(new Error("x"));
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "type code" }));
    await user.click(
      await screen.findByRole("button", { name: "consume one" }),
    );
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Error while removing from stock",
      ),
    );

    await user.click(screen.getByRole("button", { name: "add one missing" }));
    expect(mocks.updateQuantity).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "close stock" }));
    expect(mocks.camera.resumeCamera).toHaveBeenCalledTimes(1);
  });

  it("goes back, starts the camera and drops the scan context from the camera view", async () => {
    useScanStore.getState().setStorageContext({
      id: "loc-1",
      name: "Pantry",
      icon: "📦",
    } as never);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "back" }));
    expect(mocks.navigate).toHaveBeenCalledWith(-1);
    await user.click(screen.getByRole("button", { name: "start camera" }));
    expect(mocks.camera.setIsCameraActive).toHaveBeenCalledWith(true);
    await user.click(screen.getByRole("button", { name: "clear context" }));
    expect(useScanStore.getState().storageContext).toBeNull();
  });
});
