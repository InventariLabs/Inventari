import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { downloadBlob } from "@/utils/helpers";
import { DemoLabelSheet } from "./DemoLabelSheet";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

vi.mock("@/utils/helpers", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/utils/helpers")>();
  return { ...actual, downloadBlob: vi.fn() };
});

describe("DemoLabelSheet", () => {
  beforeEach(() => {
    window.URL.createObjectURL = vi.fn(() => "blob:sheet");
    window.URL.revokeObjectURL = vi.fn();
    vi.mocked(downloadBlob).mockClear();
    server.use(
      http.get(
        "/api/v1/printing/demo-label-sheet",
        () =>
          new HttpResponse(new Uint8Array([0x89, 0x50]), {
            headers: { "Content-Type": "image/png" },
          }),
      ),
    );
  });

  it("previews the sheet and gives the visitor the same file to download", async () => {
    render(<DemoLabelSheet onClose={vi.fn()} />);

    expect(
      await screen.findByAltText(
        "Preview of the demo's label sheet: location and product labels",
      ),
    ).toHaveAttribute("src", "blob:sheet");
    await userEvent.click(screen.getByRole("button", { name: "Download" }));

    expect(downloadBlob).toHaveBeenCalledWith(
      expect.any(Blob),
      "demo-label-sheet.png",
    );
  });

  it("says so in the visitor's words when the sheet will not load", async () => {
    server.use(
      http.get("/api/v1/printing/demo-label-sheet", () =>
        HttpResponse.json(null, { status: 500 }),
      ),
    );

    render(<DemoLabelSheet onClose={vi.fn()} />);

    expect(
      await screen.findByText("The label sheet could not be loaded."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeDisabled();
  });
});
