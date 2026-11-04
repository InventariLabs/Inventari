import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@/test/utils";
import DocumentScanPage from "@/modules/warehouse/pages/DocumentScanPage";
import * as scanCamera from "@/hooks/useScanCamera";
import { labelsApi } from "@/lib/api/labels";
import type { LabelScanView } from "@/types";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { scanWithHardwareScanner } from "@/test/scanner";

vi.mock("@/hooks/useScanCamera", () => ({
  useTorchAvailable: () => false,
  useScanCamera: vi.fn(),
}));

vi.mock("@/lib/api/labels", () => ({
  labelsApi: { scan: vi.fn() },
}));

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigate };
});

// The default test module list has no `warehouse`, and the number hint under
// the field reads its example from the document profile. This file puts that
// one module on top of the list every other test sees; the rest is unchanged.
vi.mock("@/contexts/ModulesContext", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/contexts/ModulesContext")>();
  const enabledModules = [...actual.FALLBACK_MODULES, "warehouse"];
  return {
    ...actual,
    useModules: () => ({
      enabledModules,
      hiddenModules: [],
      focusModule: null,
      focusStatus: "ready",
      isLoading: false,
      modulesError: false,
      isModuleEnabled: (name: string) => enabledModules.includes(name),
      refreshModules: vi.fn(),
    }),
  };
});

const toastCalls: { message: string; action?: string }[] = [];
vi.mock("sonner", () => ({
  toast: Object.assign(
    (message: string, options?: { action?: { label: string } }) => {
      toastCalls.push({ message, action: options?.action?.label });
    },
    { error: vi.fn(), success: vi.fn() },
  ),
}));

const mockCamera = (
  overrides: Partial<{
    scannerError: string | null;
    isCameraActive: boolean;
    isCameraRunning: boolean;
    setIsCameraActive: (next: boolean) => void;
    restartCamera: () => void;
    toggleTorch: () => void;
  }> = {},
) => {
  vi.mocked(scanCamera.useScanCamera).mockReturnValue({
    scannerError: null,
    isCameraActive: false,
    isCameraRunning: false,
    setIsCameraActive: vi.fn(),
    restartCamera: vi.fn(),
    toggleTorch: vi.fn(),
    isTorchOn: false,
    ...overrides,
  } as unknown as ReturnType<typeof scanCamera.useScanCamera>);
};

const submit = (code: string) => {
  const input = screen.getByPlaceholderText(/document number or scanned code/i);
  fireEvent.change(input, { target: { value: code } });
  fireEvent.submit(input.closest("form")!);
};

const unrecognized = () =>
  Object.assign(new Error("not recognized"), {
    isAxiosError: true,
    response: {
      status: 404,
      data: { detail: { code: "SCAN_UNRECOGNIZED", message: "Unknown code" } },
    },
  });

/** The default profile: the shape `models/profile.py` ships, which numbers
 *  `IN/2026/001` — the example the hint used to spell out wrongly. */
const defaultProfile = {
  numbering_format: "{TYPE}/{YEAR}/{SEQ:03d}",
  number_padding: 3,
  type_labels: null,
};

beforeEach(() => {
  mockCamera();
  navigate.mockReset();
  toastCalls.length = 0;
  vi.mocked(labelsApi.scan).mockReset();
  server.use(
    http.get("*/warehouse/profile", () => HttpResponse.json(defaultProfile)),
  );
});

describe("DocumentScanPage", () => {
  it("shows an empty-state hint when the page loads with no camera and no error", () => {
    render(<DocumentScanPage />);
    expect(screen.getByTestId("scan-empty-state")).toBeInTheDocument();
  });

  it("does NOT show the empty state once the camera is active", () => {
    mockCamera({ isCameraActive: true });
    render(<DocumentScanPage />);
    expect(screen.queryByTestId("scan-empty-state")).not.toBeInTheDocument();
  });

  it("resolves a typed number through the shared registry, not its own lookup", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "document",
      label_code: "IN/2026/049",
      message: "",
      action: "open_document",
      document: {
        id: "d1",
        number: "IN/2026/049",
        status: "DRAFT",
        type: "IN",
      },
      document_mode: "continue",
    } as LabelScanView);

    render(<DocumentScanPage />);
    submit("IN/2026/049");

    await waitFor(() =>
      expect(labelsApi.scan).toHaveBeenCalledWith("IN/2026/049"),
    );
    expect(navigate).toHaveBeenCalledWith("/warehouse/documents/d1#edit");
  });

  it("resolves a code a hardware scanner reads, with no field focused", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "document",
      label_code: "IN/2026/049",
      message: "",
      action: "open_document",
      document: {
        id: "d1",
        number: "IN/2026/049",
        status: "DRAFT",
        type: "IN",
      },
      document_mode: "continue",
    } as LabelScanView);

    render(<DocumentScanPage />);
    expect(
      screen.getByText("A barcode scanner can be used on this screen"),
    ).toBeInTheDocument();
    scanWithHardwareScanner("IN/2026/049", document.body);

    await waitFor(() =>
      expect(labelsApi.scan).toHaveBeenCalledWith("IN/2026/049"),
    );
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/warehouse/documents/d1#edit"),
    );
  });

  it("resolves its own printed QR, which wraps the number in a URL", async () => {
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "document",
      label_code: "IN/2026/049",
      message: "",
      action: "open_document",
      document: {
        id: "d1",
        number: "IN/2026/049",
        status: "COMPLETED",
        type: "IN",
      },
      document_mode: "preview",
    } as LabelScanView);

    render(<DocumentScanPage />);
    submit("https://wh.example.test/scan?code=IN/2026/049");

    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("/warehouse/documents/d1"),
    );
  });

  it("opens what is on a scanned location instead of saying not found", async () => {
    server.use(
      http.get("/api/v1/stock-quants", ({ request }) => {
        expect(new URL(request.url).searchParams.get("location_id")).toBe("s1");
        return HttpResponse.json({
          items: [
            {
              id: "q1",
              product_template_id: "p1",
              location_id: "s2",
              quantity: "4.000",
              reserved_quantity: "0",
              available_quantity: "4.000",
              product_name: "Rye flour",
              uom_symbol: "kg",
              location_name: "Shelf 2",
              lot_name: "L-7",
              expiry_date: "2031-05-01",
            },
          ],
          total: 1,
          offset: 0,
          limit: 100,
        });
      }),
    );
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "storage_context",
      label_code: "LOC-7",
      message: "",
      action: "set_storage_context",
      location: { id: "s1", name: "Cold Storage A", icon: "📦" },
    } as LabelScanView);

    render(<DocumentScanPage />);
    submit("LOC-7");

    expect(await screen.findByText("Rye flour")).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: /Cold Storage A/ }),
    ).toBeInTheDocument();
    expect(toastCalls).toHaveLength(0);
    expect(screen.queryByText(/not recognized/i)).not.toBeInTheDocument();
  });

  it("offers to print the scanned shelf's label from the sheet it opens", async () => {
    server.use(
      http.get("/api/v1/stock-quants", () =>
        HttpResponse.json({ items: [], total: 0, offset: 0, limit: 100 }),
      ),
    );
    vi.mocked(labelsApi.scan).mockResolvedValue({
      status: "storage_context",
      label_code: "LOC-7",
      message: "",
      action: "set_storage_context",
      location: { id: "s1", name: "Cold Storage A", icon: "📦" },
    } as LabelScanView);

    render(<DocumentScanPage />);
    submit("LOC-7");

    expect(
      await screen.findByRole("button", { name: "Print label" }),
    ).toBeInTheDocument();
  });

  it("keeps the not-recognized card for a code no provider knows", async () => {
    vi.mocked(labelsApi.scan).mockRejectedValue(unrecognized());

    render(<DocumentScanPage />);
    submit("ZZZZZ");

    await waitFor(() =>
      expect(screen.getAllByText(/not recognized/i).length).toBeGreaterThan(0),
    );
    expect(toastCalls).toHaveLength(0);
  });

  it("offers the product search with the unrecognized code in it", async () => {
    vi.mocked(labelsApi.scan).mockRejectedValue(unrecognized());

    render(<DocumentScanPage />);
    submit("BRG-6204");

    fireEvent.click(
      await screen.findByRole("button", { name: /search for this code/i }),
    );
    expect(navigate).toHaveBeenCalledWith("/inventory/items?search=BRG-6204");
  });

  it("shows a 'no camera detected' fallback when navigator.mediaDevices is unavailable", async () => {
    const original = (
      navigator as Navigator & {
        mediaDevices?: MediaDevices;
      }
    ).mediaDevices;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: undefined,
    });
    render(<DocumentScanPage />);
    await waitFor(() =>
      expect(screen.getByTestId("scan-no-camera-fallback")).toBeInTheDocument(),
    );
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: original,
    });
  });

  // The switch carried "Scanning…" from `isCameraActive` — the user's wish
  // to scan — so a refused camera left the blue label glowing directly over
  // the sentence explaining the refusal. The screen said both things at once.
  it("names the device, not the wish to scan", () => {
    mockCamera({
      isCameraActive: true,
      isCameraRunning: false,
      scannerError: "This camera does not meet the scanner's requirements.",
    });

    const { unmount } = render(<DocumentScanPage />);

    expect(
      screen.queryByRole("button", { name: "Scanning…" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Scan document" }),
    ).toBeInTheDocument();

    unmount();

    mockCamera({ isCameraActive: true, isCameraRunning: true });
    render(<DocumentScanPage />);

    expect(
      screen.getByRole("button", { name: "Scanning…" }),
    ).toBeInTheDocument();
  });

  it("offers the refusal with the manual way out and the name the other scanner uses", () => {
    mockCamera({
      isCameraActive: true,
      isCameraRunning: false,
      scannerError: "This camera does not meet the scanner's requirements.",
    });

    render(<DocumentScanPage />);

    expect(
      screen.getByText("This camera does not meet the scanner's requirements."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("You can also type the code by hand below."),
    ).toBeInTheDocument();
    // The inventory scanner calls this button "Try again"; this screen called
    // the same action "Retry".
    expect(
      screen.getByRole("button", { name: "Try again" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("scan-aim-frame")).not.toBeInTheDocument();
  });

  // html5-qrcode sets the reader's position to `relative` when it starts, so
  // an `absolute inset-0` reader grew to the height of the whole picture and
  // the 4:3 box showed only its top, while the library centres the region it
  // decodes on the whole picture: the frame sat partly or wholly below the
  // box. Sized by width and height instead, the reader stays the box, and the
  // picture is centred in it.
  it("keeps the camera picture centred in the visible box", () => {
    mockCamera({ isCameraActive: true, isCameraRunning: true });
    render(<DocumentScanPage />);

    expect(document.getElementById("qr-reader")).toHaveClass(
      "h-full",
      "w-full",
      "flex",
      "flex-col",
      "justify-center",
    );
  });

  // The library's own shading is sized for the whole picture, so it cannot
  // mark the region in a box that shows only part of it. The frame is drawn
  // from the size the camera hook publishes for the region it decodes, and
  // centred like that region.
  it("draws the aiming frame from the region the decoder reads", () => {
    mockCamera({ isCameraActive: true, isCameraRunning: true });
    render(<DocumentScanPage />);

    const box = document.getElementById("qr-reader")!.parentElement!;
    const frame = screen.getByTestId("scan-aim-frame");
    expect(frame.parentElement).toBe(box);
    expect(frame).toHaveClass(
      "w-[var(--aim-w,0px)]",
      "h-[var(--aim-h,0px)]",
      "left-1/2",
      "top-1/2",
      "-translate-x-1/2",
      "-translate-y-1/2",
    );
    expect(box).toHaveClass("[&_#qr-reader>div]:!border-0");
  });

  // Wherever the window is wide and low (a phone on its side, a laptop) the
  // 4:3 box was taller than the window, and the aiming frame lay below its
  // bottom edge. The box is capped by what is left of the window, but never
  // below a floor: with the keyboard open that cap is 0 and html5-qrcode
  // throws on a box under 50 px.
  it("caps the camera box by the window height, with a floor", () => {
    mockCamera({ isCameraActive: true, isCameraRunning: true });
    render(<DocumentScanPage />);

    const box = document.getElementById("qr-reader")!.parentElement!;
    expect(box).toHaveClass(
      "aspect-[4/3]",
      "w-full",
      "max-h-[max(4rem,calc(100dvh-16rem))]",
    );
  });
});

/**
 * The example under the field used to be written into the catalogue:
 * "Receipt/2026/0001" in four languages, "PZ/2026/0001" in Polish — numbers
 * this configuration never produces, since `{TYPE}` writes the receipt's
 * neutral short code and the sequence is padded to the profile's own width.
 * The hint now takes its example from the organization's numbering format, so
 * what it promises is what a scan of a printed number can find.
 */
describe("DocumentScanPage — the example number follows the profile", () => {
  // The line under the manual field — the only sentence carrying an example.
  const hint = () => screen.getByText(/A document number such as/);

  it("reads the number the default profile produces", async () => {
    render(<DocumentScanPage />);

    const example = `IN/${new Date().getFullYear()}/001`;
    await waitFor(() => expect(hint()).toHaveTextContent(example));
    // Neither a type name nor a paperwork code stands where the number is.
    expect(hint()).not.toHaveTextContent(/Receipt\/\d{4}\//);
    expect(hint()).not.toHaveTextContent(/PZ\/\d{4}\//);
  });

  it("follows the organisation's own format, labels and padding included", async () => {
    server.use(
      http.get("*/warehouse/profile", () =>
        HttpResponse.json({
          numbering_format: "{TYPE_LABEL}/{YEAR}/{MONTH}/{SEQ:04d}",
          number_padding: 4,
          type_labels: { IN: "PZ" },
        }),
      ),
    );

    render(<DocumentScanPage />);

    const now = new Date();
    const month = String(now.getMonth() + 1).padStart(2, "0");
    const example = `PZ/${now.getFullYear()}/${month}/0001`;
    await waitFor(() => expect(hint()).toHaveTextContent(example));
  });
});
