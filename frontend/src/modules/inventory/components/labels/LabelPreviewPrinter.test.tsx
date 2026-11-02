import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/mocks/server";
import type { LabelPool } from "@/types";
import { LabelPreviewModal, type PrintSettings } from "./LabelPreviewModal";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => ["printing"],
}));

// What the preview asks the generator for is the question here; that the
// preview shows the generator's own image is LabelPreviewModal.test.tsx's.
const previewed = vi.fn();
vi.mock("@/modules/inventory/hooks/useLabelSheetPreview", () => ({
  useLabelSheetPreview: (request: unknown) => {
    previewed(request);
    return { url: null, isLoading: false, failed: false };
  },
}));

const label = {
  id: "lbl-1",
  short_code: "STM-K9XP",
  description: "Minced beef",
  label_type: "GENERIC",
  status: "FREE",
} as unknown as LabelPool;

const desk = {
  id: "a-1",
  name: "brother-desk",
  printer_type: "brother-p710bt",
  last_seen_at: "2026-10-07T19:00:00Z",
  online: true,
};

// A square QR with its code — the combination that came out of the tape
// printer as a strip the preview never showed, when the printer's own size
// decided the label.
const chosen: PrintSettings = {
  width: 30,
  height: 30,
  publicUrl: "https://inventari.example",
  customDescription: "",
  qrOnly: true,
  copiesPerLabel: 2,
  showCode: true,
};

function Harness() {
  const [settings, setSettings] = useState(chosen);
  return (
    <LabelPreviewModal
      open
      onClose={vi.fn()}
      selectedLabels={[label]}
      printSettings={settings}
      setPrintSettings={setSettings}
      onDownload={vi.fn()}
    />
  );
}

let queryClient: QueryClient;

function renderHarness() {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  );
}

const lastPreview = () =>
  previewed.mock.calls[previewed.mock.calls.length - 1][0] as Record<
    string,
    unknown
  >;

describe("LabelPreviewModal — one label for the file and the printer", () => {
  beforeEach(() => {
    previewed.mockClear();
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(onePage([desk])),
      ),
    );
  });

  // The printer list can still be in flight when a test passes. Under a
  // loaded full run that read reached the server after this test's handlers
  // were reset and was charged to the next test as an unmocked request.
  afterEach(async () => {
    await waitFor(() => expect(queryClient.isFetching()).toBe(0));
  });

  it("sends the printer the label it previews, at the preview's size", async () => {
    let queued: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/printing/jobs", async ({ request }) => {
        queued = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "job-1" }, { status: 201 });
      }),
    );

    renderHarness();

    await userEvent.click(
      await screen.findByRole("button", { name: /send to printer/i }),
    );

    await waitFor(() => expect(queued).not.toBeNull());
    expect(queued).toMatchObject({
      agent_id: "a-1",
      label_ids: ["lbl-1"],
      qr_only: true,
      show_code: true,
      copies: 2,
      width_mm: 30,
      height_mm: 30,
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /send to printer/i }),
      ).not.toBeDisabled(),
    );
  });

  it("previews the size the reader set, whatever printer is connected", async () => {
    renderHarness();

    await screen.findByRole("button", { name: /send to printer/i });
    const width = screen.getByRole("spinbutton", { name: /width/i });
    expect(width).not.toBeDisabled();
    await userEvent.clear(width);
    await userEvent.type(width, "62");

    await waitFor(() =>
      expect(lastPreview()).toMatchObject({ width: 62, height: 30 }),
    );
    expect(lastPreview()).not.toHaveProperty("media");
    expect(
      screen.queryByRole("combobox", { name: /printed on/i }),
    ).not.toBeInTheDocument();
  });
});
