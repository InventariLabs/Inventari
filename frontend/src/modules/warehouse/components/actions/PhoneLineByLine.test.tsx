import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import { PhoneLineByLine } from "./PhoneLineByLine";

const scan = vi.hoisted(() => vi.fn());
const camera = vi.hoisted(() => ({ onCode: (_code: string) => {} }));
const toastWarning = vi.hoisted(() => vi.fn());

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: toastWarning,
  }),
}));

vi.mock("@/lib/api/labels", () => ({ labelsApi: { scan } }));
// The camera is a live device: the test hands the screen the code it read.
vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: ({
    onCodeScanned,
  }: {
    onCodeScanned: (code: string) => void;
  }) => {
    camera.onCode = onCodeScanned;
    return {
      scannerError: null,
      isCameraActive: false,
      isTorchOn: false,
      toggleTorch: vi.fn(),
      restartCamera: vi.fn(),
    };
  },
}));

function renderEntry() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <PhoneLineByLine
      lines={[]}
      stockLocationId={null}
      merge={false}
      wholeRecord={false}
      lineErrors={{}}
      onAdd={vi.fn()}
      onRemove={vi.fn()}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>{children}</BrowserRouter>
        </QueryClientProvider>
      ),
    },
  );
}

describe("PhoneLineByLine", () => {
  it("proposes two pieces when one product is read twice during its lookup", async () => {
    const answers: (() => void)[] = [];
    scan.mockImplementation(
      () =>
        new Promise((resolve) => {
          answers.push(() =>
            resolve({
              status: "assigned",
              label_code: "STM-EHBH",
              action: "show_quick_actions",
              item: { id: "item-1", name: "Lean Quark", uom_id: null },
            }),
          );
        }),
    );
    renderEntry();

    act(() => {
      camera.onCode("5901234123457");
      camera.onCode("5901234123457");
    });
    await act(async () => answers[0]());
    await waitFor(() => expect(answers).toHaveLength(2));
    await act(async () => answers[1]());

    expect(
      screen.getByLabelText(/How many.*Lean Quark/, { selector: "input" }),
    ).toHaveDisplayValue("2");
  });

  it("keeps the product on the card and says another one was not added", async () => {
    scan.mockImplementation(async (code: string) => ({
      status: "assigned",
      label_code: code,
      action: "show_quick_actions",
      item: { id: code, name: `Goods ${code}`, uom_id: null },
    }));
    renderEntry();

    await act(async () => {
      camera.onCode("AAA");
      camera.onCode("BBB");
    });

    await waitFor(() => expect(toastWarning).toHaveBeenCalledTimes(1));
    expect(toastWarning.mock.calls[0][0]).toContain("Goods BBB was not added");
    expect(
      screen.getByLabelText(/How many.*Goods AAA/, { selector: "input" }),
    ).toHaveDisplayValue("1");
  });
});
