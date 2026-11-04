import React from "react";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { labelsApi } from "@/lib/api/labels";
import type { LabelScanView } from "@/types";

import AddEquipmentPage from "../pages/AddEquipmentPage";

/**
 * The scan button beside Barcode / EAN, wired into the form.
 *
 * The unit tests pin what a scan result means; these pin that the screen
 * actually asks. The defect they close was the wiring: the handler wrote
 * whatever the camera decoded into Barcode / EAN, so a label QR put its
 * whole address there. Measured before the fix: scan the QR of a label
 * stuck to another product and the field reads
 * 'http://localhost:5773/s/STM-EHBH'.
 */

// The camera is not what this file is about: the hook's callback is captured
// and fired by hand, exactly as a decode would. `vi.hoisted` because
// `vi.mock` factories are lifted above the imports.
const { codeScanned, toast } = vi.hoisted(() => ({
  codeScanned: [] as Array<(code: string) => void>,
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));
vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: ({
    onCodeScanned,
  }: {
    onCodeScanned: (code: string) => void;
  }) => {
    codeScanned.push(onCodeScanned);
    return {
      isCameraActive: true,
      scannerError: null,
      isTorchOn: false,
      toggleTorch: vi.fn(),
      restartCamera: vi.fn(),
    };
  },
}));
vi.mock("sonner", () => ({ toast }));

beforeEach(() => {
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "locations:read",
    "categories:read",
  ]);
  codeScanned.length = 0;
  toast.mockClear();
  toast.success.mockClear();
  toast.error.mockClear();
});

afterEach(() => {
  signOut();
  vi.restoreAllMocks();
});

function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {children}
    </PageHeaderContext.Provider>
  );
}

async function renderAddPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(<AddEquipmentPage />, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <MemoryRouter initialEntries={["/equipment/add"]}>
            <PageHeaderHost>
              <Routes>
                <Route path="/equipment/add" element={children} />
              </Routes>
            </PageHeaderHost>
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>
    ),
  });
  await screen.findByLabelText(/barcode/i);
}

async function scan(code: string) {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /^scan$/i }));
  await act(async () => {
    codeScanned.at(-1)?.(code);
  });
}

const assignedLabel = {
  status: "assigned",
  label_code: "STM-EHBH",
  message_key: "scan:result.product",
  message_params: { product: "Spaghetti 500g" },
  action: "show_quick_actions",
  item: { id: "i1", name: "Spaghetti 500g" },
} as unknown as LabelScanView;

const blankLabel = {
  status: "unassigned",
  label_code: "STM-Y3GI",
  message_key: "scan:result.labelReady",
  action: "show_quick_add",
} as LabelScanView;

describe("AddEquipmentPage — scanning into Barcode / EAN", () => {
  it("never writes a label's address into the field; it names the product instead", async () => {
    vi.spyOn(labelsApi, "scan").mockResolvedValue(assignedLabel);

    await renderAddPage();
    await scan("http://localhost:5773/s/STM-EHBH");

    await waitFor(() =>
      expect(toast).toHaveBeenCalledWith(
        expect.stringContaining("Spaghetti 500g"),
        // The resolver's offer to open the product elsewhere.
        expect.objectContaining({ action: expect.anything() }),
      ),
    );
    const barcode = screen.getByLabelText(/barcode/i) as HTMLInputElement;
    expect(barcode.value).toBe("");
    expect(barcode.value).not.toContain("/s/");
    // Nothing took the taken label's place either.
    expect(screen.getByText(/no label assigned/i)).toBeInTheDocument();
  });

  it("sends a blank label's code to the label field, not to Barcode / EAN", async () => {
    vi.spyOn(labelsApi, "scan").mockResolvedValue(blankLabel);

    await renderAddPage();
    await scan("http://localhost:5773/s/STM-Y3GI");

    expect(await screen.findByText("STM-Y3GI")).toBeInTheDocument();
    const barcode = screen.getByLabelText(/barcode/i) as HTMLInputElement;
    expect(barcode.value).toBe("");
  });

  it("still records a product barcode, naming the product it belongs to", async () => {
    vi.spyOn(labelsApi, "scan").mockResolvedValue({
      status: "product_stock",
      label_code: "5907770001112",
      message_key: "scan:result.product",
      message_params: { product: "Spaghetti 500g" },
      action: "show_stock_actions",
      stock_summary: {
        total_quantity: 1,
        unit: "pcs",
        template: { id: "t1", name: "Spaghetti 500g" },
        items: [],
      },
    } as unknown as LabelScanView);

    await renderAddPage();
    await scan("5907770001112");

    await waitFor(() => {
      const barcode = screen.getByLabelText(/barcode/i) as HTMLInputElement;
      expect(barcode.value).toBe("5907770001112");
    });
    expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("Spaghetti 500g"),
    );
  });
});
