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

describe("BarcodeLabelSheet — product labels", () => {
  const previewWith = (withDetails: number) => {
    window.URL.createObjectURL = vi.fn(() => "blob:products");
    window.URL.revokeObjectURL = vi.fn();
    server.use(
      http.get("/api/v1/printing/agents", () => HttpResponse.json(onePage([]))),
      http.post(
        "/api/v1/printing/product-labels/png",
        () =>
          new HttpResponse(new Uint8Array([0x89, 0x50]), {
            headers: {
              "Content-Type": "image/png",
              "X-Labels-Without-Code": "0",
              "X-Labels-With-Details": String(withDetails),
            },
          }),
      ),
    );
  };
  const detailsBox = () =>
    screen.getByRole("checkbox", { name: "Lot and expiry date" });

  it("does not show the lot option ticked when no product has a lot or an expiry date", async () => {
    previewWith(0);
    render(
      <BarcodeLabelSheet target={{ itemIds: ["i-1"] }} onClose={vi.fn()} />,
    );

    await screen.findByText(/nothing to add/);

    expect(detailsBox()).toBeDisabled();
    expect(detailsBox()).not.toBeChecked();
  });

  it("keeps the lot option ticked when a product has something to print", async () => {
    previewWith(1);
    render(
      <BarcodeLabelSheet target={{ itemIds: ["i-1"] }} onClose={vi.fn()} />,
    );

    await screen.findByAltText(/Preview/);

    expect(detailsBox()).toBeEnabled();
    expect(detailsBox()).toBeChecked();
  });
});

describe("BarcodeLabelSheet — batch labels", () => {
  let previewed: Record<string, unknown> | null;
  let queued: Record<string, unknown> | null;

  beforeEach(() => {
    previewed = null;
    queued = null;
    window.URL.createObjectURL = vi.fn(() => "blob:batch");
    window.URL.revokeObjectURL = vi.fn();
    server.use(
      http.get("/api/v1/printing/agents", () =>
        HttpResponse.json(
          onePage([
            {
              id: "a-1",
              name: "kitchen",
              printer_type: "brother-p710bt",
              last_seen_at: "2026-11-01T10:00:00Z",
              online: true,
            },
          ]),
        ),
      ),
      http.post("/api/v1/printing/lot-labels/png", async ({ request }) => {
        previewed = (await request.json()) as Record<string, unknown>;
        return new HttpResponse(new Uint8Array([0x89, 0x50]), {
          headers: { "Content-Type": "image/png" },
        });
      }),
      http.post("/api/v1/printing/jobs", async ({ request }) => {
        queued = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ id: "job-1" }, { status: 201 });
      }),
    );
  });

  it("previews one label and sends one per unit the run made", async () => {
    const onClose = vi.fn();
    render(
      <BarcodeLabelSheet
        target={{ lotIds: ["lot-1"] }}
        initialCopies={48}
        title="Jar labels"
        onClose={onClose}
      />,
    );

    expect(
      await screen.findByAltText("Preview of one batch label"),
    ).toHaveAttribute("src", "blob:batch");
    expect(previewed).toMatchObject({ lot_ids: ["lot-1"], copies: 1 });
    expect(screen.getByText("Jar labels")).toBeInTheDocument();
    expect(screen.getByTestId("label-sheet-copies-input")).toHaveValue(48);
    expect(
      screen.queryByRole("checkbox", { name: "Lot and expiry date" }),
    ).toBeNull();
    await userEvent.click(
      await screen.findByRole("button", { name: "Send to printer" }),
    );

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(queued).toMatchObject({ lot_ids: ["lot-1"], copies: 48 });
  });
});
