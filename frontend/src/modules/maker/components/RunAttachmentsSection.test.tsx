import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { RunAttachmentsSection } from "@/modules/maker/components/RunAttachmentsSection";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

const photo = {
  id: "att-1",
  production_order_id: "ord-1",
  original_name: "jars.png",
  content_type: "image/png",
  size_bytes: 2048,
  url: "/uploads/org/maker/ord-1/a.png",
  created_at: "2026-11-01T10:00:00Z",
};

describe("RunAttachmentsSection", () => {
  let uploads = 0;
  let deleted: string | null = null;

  beforeEach(() => {
    uploads = 0;
    deleted = null;
    server.use(
      http.get("*/api/v1/maker/production/orders/ord-1/attachments", () =>
        HttpResponse.json(onePage([photo])),
      ),
      http.post("*/api/v1/maker/production/orders/ord-1/attachments", () => {
        uploads += 1;
        return HttpResponse.json(photo, { status: 201 });
      }),
      http.delete(
        "*/api/v1/maker/production/orders/ord-1/attachments/:id",
        ({ params }) => {
          deleted = String(params.id);
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );
  });

  it("lists the run's files as links to open", async () => {
    render(<RunAttachmentsSection orderId="ord-1" />);

    expect(
      await screen.findByRole("link", { name: "jars.png" }),
    ).toHaveAttribute("href", "/uploads/org/maker/ord-1/a.png");
  });

  it("files a picked photo under the run", async () => {
    render(<RunAttachmentsSection orderId="ord-1" />);
    await screen.findByText("jars.png");

    const picker = screen.getByTestId("maker-run-attachment-input");
    fireEvent.change(picker, {
      target: { files: [new File(["x"], "more.png", { type: "image/png" })] },
    });

    await waitFor(() => expect(uploads).toBe(1));
  });

  it("removes a file only after asking", async () => {
    render(<RunAttachmentsSection orderId="ord-1" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove jars.png" }),
    );

    expect(deleted).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(deleted).toBe("att-1"));
  });
});
