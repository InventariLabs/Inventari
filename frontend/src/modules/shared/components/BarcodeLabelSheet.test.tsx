import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { BarcodeLabelSheet } from "./BarcodeLabelSheet";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

describe("BarcodeLabelSheet — shelf labels", () => {
  let queued: Record<string, unknown> | null;

  beforeEach(() => {
    queued = null;
    window.URL.createObjectURL = vi.fn(() => "blob:shelves");
    window.URL.revokeObjectURL = vi.fn();
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(
          onePage([
            {
              id: "a-1",
              name: "dock",
              printer_type: "zebra",
              last_seen_at: "2026-10-22T10:00:00Z",
              online: true,
            },
          ]),
        ),
      ),
      http.post(
        "/api/v1/printing/location-labels/png",
        () =>
          new HttpResponse(new Uint8Array([0x89, 0x50]), {
            headers: {
              "Content-Type": "image/png",
              "X-Labels-Without-Code": "1",
            },
          }),
      ),
      http.post("/api/v1/printing/jobs", async ({ request }) => {
        queued = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "job-1" }, { status: 201 });
      }),
    );
  });

  it("sends the shelves to the printer as Code 128, with the QR when asked", async () => {
    const onClose = vi.fn();
    render(
      <BarcodeLabelSheet
        target={{ storageIds: ["s-1", "s-2"] }}
        onClose={onClose}
      />,
    );

    expect(
      await screen.findByAltText("Preview of the location labels"),
    ).toHaveAttribute("src", "blob:shelves");
    expect(
      screen.getByText(/1 of the chosen locations has no code/),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("checkbox", {
        name: "QR beside the bars, for a phone camera",
      }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Send to printer" }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(queued).toMatchObject({
      location_ids: ["s-1", "s-2"],
      bars: true,
      qr: true,
    });
    expect(queued).not.toHaveProperty("details");
  });
});
