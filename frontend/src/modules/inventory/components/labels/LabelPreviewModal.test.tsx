import { render, screen, waitFor, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { server } from "@/test/mocks/server";
import type { LabelPool } from "@/types";
import { LabelPreviewModal, type PrintSettings } from "./LabelPreviewModal";

const label = {
  id: "lbl-1",
  short_code: "STM-K9XP",
  description: "Minced beef",
  label_type: "GENERIC",
  status: "FREE",
} as unknown as LabelPool;

const settings: PrintSettings = {
  width: 50,
  height: 24,
  publicUrl: "https://inventari.example",
  customDescription: "",
  qrOnly: false,
  copiesPerLabel: 1,
  showCode: false,
};

function renderModal(overrides: Partial<PrintSettings> = {}) {
  // The footer's "Send to printer" asks the print queue for printers.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <LabelPreviewModal
        open
        onClose={vi.fn()}
        selectedLabels={[label]}
        printSettings={{ ...settings, ...overrides }}
        setPrintSettings={vi.fn()}
        onDownload={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

/** Every request the window makes for a rendered sheet. */
function captureRenders() {
  const asked: URLSearchParams[] = [];
  server.use(
    http.get("/api/v1/labels/pool/export/png", ({ request }) => {
      asked.push(new URL(request.url).searchParams);
      return new HttpResponse(new Blob(["png"]), {
        headers: { "Content-Type": "image/png" },
      });
    }),
  );
  return asked;
}

describe("LabelPreviewModal — the preview is the file", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.URL.createObjectURL = vi.fn(() => "blob:sheet");
    window.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the generator's own image, not a second composition of it", async () => {
    // The window drew its own label in HTML — a box in the label's
    // proportions, a QR at 90% of its height, the code at a sixth — while
    // the generator drew another one on a canvas three quarters as tall
    // with the code at 38%. The file was the composition nobody had seen.
    const asked = captureRenders();

    renderModal();
    await act(() => vi.advanceTimersByTimeAsync(500));

    const image = await screen.findByRole("img", { name: /label sheet/i });
    expect(image).toHaveAttribute("src", "blob:sheet");
    expect(asked).toHaveLength(1);
  });

  it("asks for the same file the download does, without spending the pool", async () => {
    const asked = captureRenders();

    renderModal({ copiesPerLabel: 3 });
    await act(() => vi.advanceTimersByTimeAsync(500));

    await waitFor(() => expect(asked).toHaveLength(1));
    const params = asked[0];
    expect(params.get("width")).toBe("50");
    expect(params.get("height")).toBe("24");
    // One geometry: nothing about a printer goes into the file.
    expect(params.has("media")).toBe(false);
    expect(params.getAll("label_ids")).toEqual(["lbl-1", "lbl-1", "lbl-1"]);
    // Looking at a label must not mark it printed.
    expect(params.get("mark_printed")).toBe("false");
  });

  it("says so when the sheet cannot be rendered", async () => {
    server.use(
      http.get(
        "/api/v1/labels/pool/export/png",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderModal();
    await act(() => vi.advanceTimersByTimeAsync(500));

    expect(
      await screen.findByText(/preview could not be rendered/i),
    ).toBeInTheDocument();
  });
});

describe("LabelPreviewModal — the frame takes the sheet's proportions", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    window.URL.createObjectURL = vi.fn(() => "blob:sheet");
    window.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /** jsdom never decodes the image, so the load carries the real dims. */
  async function loadSheetWith(dims: { w: number; h: number }) {
    const image = (await screen.findByRole("img", {
      name: /label sheet/i,
    })) as HTMLImageElement;
    Object.defineProperty(image, "naturalWidth", { value: dims.w });
    Object.defineProperty(image, "naturalHeight", { value: dims.h });
    await act(() => {
      image.dispatchEvent(new Event("load"));
    });
    return image;
  }

  it("fills the modal's width on a long sheet, the height from the aspect", async () => {
    // A sheet of three labels came back 1052x128 while the frame sized
    // itself from one label's height setting — the sheet landed as a thin
    // strip swimming in an empty box three times too tall.
    captureRenders();

    renderModal({ copiesPerLabel: 3, height: 12 });
    await act(() => vi.advanceTimersByTimeAsync(500));

    const image = await loadSheetWith({ w: 1052, h: 128 });
    // One label of the sheet displays at the mm setting (12 mm x 12 px/mm);
    // the whole sheet takes that scale across its own width — and the
    // panel caps it, so a wide sheet fills the modal edge to edge.
    expect(image.style.width).toBe("1184px");
    expect(image.style.maxWidth).toBe("100%");
    expect(image.style.height).toBe("auto");
  });

  it("keeps the label's own size when the sheet is a single label", async () => {
    captureRenders();

    renderModal();
    await act(() => vi.advanceTimersByTimeAsync(500));

    const image = await loadSheetWith({ w: 591, h: 283 });
    // The file arrives at the renderer's own resolution (roughly 300 dpi
    // here), not at the preview's px/mm — the scale comes from how the
    // sheet's height maps onto the label height, so a 50x24 label shows at
    // its familiar size, whatever the dpi was.
    expect(image.style.width).toBe("601px");
    expect(image.style.maxWidth).toBe("100%");
    expect(image.style.height).toBe("auto");
  });
});
