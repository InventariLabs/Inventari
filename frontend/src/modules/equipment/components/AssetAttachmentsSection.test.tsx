import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { toast } from "sonner";
import { signInWith, signOut } from "@/test/auth";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { AssetAttachmentsSection } from "./AssetAttachmentsSection";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

function attachment(id: string, url: string) {
  return {
    id,
    item_id: "item-1",
    original_name: `file-${id}.pdf`,
    size_bytes: 1024,
    file_type: "OTHER",
    content_type: "application/pdf",
    url,
    created_at: "2026-01-01T00:00:00Z",
  };
}

async function renderWith(urls: string[]) {
  server.use(
    http.get("*/equipment/:id/attachments", () =>
      HttpResponse.json(onePage(urls.map((u, i) => attachment(String(i), u)))),
    ),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AssetAttachmentsSection itemId="item-1" />
    </QueryClientProvider>,
  );
  await screen.findByText("file-0.pdf");
}

describe("AssetAttachmentsSection link gate", () => {
  it.each(["javascript:alert(1)", "data:text/html,x", "//evil.example/x"])(
    "renders %s as no link at all",
    async (url) => {
      await renderWith([url]);
      expect(screen.queryAllByRole("link")).toHaveLength(0);
    },
  );

  it("keeps relative uploads and https links clickable", async () => {
    await renderWith(["/uploads/a.pdf", "https://cdn.example/b.pdf"]);
    const hrefs = screen
      .getAllByRole("link")
      .map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/uploads/a.pdf", "https://cdn.example/b.pdf"]);
  });
});

/**
 * Uploading and deleting are the section's two writes. The failures
 * caught: the chosen attachment type not travelling with the file, a
 * delete sent without (or despite cancelling) the confirmation, a list
 * that does not refetch after either, and a failure reported as nothing.
 */
describe("AssetAttachmentsSection — upload and delete", () => {
  let listed: number;

  beforeEach(() => {
    listed = 0;
    signInWith(["equipment:read", "equipment:write"]);
    server.use(
      http.get("*/equipment/:id/attachments", () => {
        listed++;
        return HttpResponse.json(
          onePage([attachment("a1", "/uploads/manual.pdf")]),
        );
      }),
    );
  });

  afterEach(() => {
    signOut();
  });

  function renderSection() {
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <AssetAttachmentsSection itemId="item-1" />
      </QueryClientProvider>,
    );
    return userEvent.setup();
  }

  function pickFile() {
    const input = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: {
        files: [new File(["%PDF"], "invoice.pdf", { type: "application/pdf" })],
      },
    });
  }

  it("uploads the file as the chosen type and refreshes the list", async () => {
    let body = "";
    server.use(
      http.post("*/equipment/item-1/attachments", async ({ request }) => {
        body = await request.text();
        return HttpResponse.json(attachment("a2", "/uploads/invoice.pdf"));
      }),
    );
    renderSection();
    await screen.findByText("file-a1.pdf");

    fireEvent.click(screen.getByRole("combobox", { name: "Attachment type" }));
    fireEvent.click(screen.getByRole("option", { name: "Invoice" }));
    pickFile();

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("File uploaded"),
    );
    expect(body).toMatch(/name="file_type"\r\n\r\nINVOICE/);
    await waitFor(() => expect(listed).toBe(2));
  });

  it("says why an upload was refused", async () => {
    server.use(
      http.post("*/equipment/item-1/attachments", () =>
        HttpResponse.json({ detail: "Unsupported file type" }, { status: 415 }),
      ),
    );
    renderSection();
    await screen.findByText("file-a1.pdf");

    pickFile();
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Unsupported file type"),
    );
  });

  it("deletes a file only after the confirmation, and says so", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("*/equipment/item-1/attachments/a1", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = renderSection();
    await screen.findByText("file-a1.pdf");

    await user.click(
      screen.getByRole("button", { name: "Delete file-a1.pdf" }),
    );
    let dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText('This permanently removes "file-a1.pdf".'),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(deleted).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: "Delete file-a1.pdf" }),
    );
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("File deleted"),
    );
    expect(deleted).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(listed).toBe(2));
  });

  it("reports a delete the server refused", async () => {
    server.use(
      http.delete("*/equipment/item-1/attachments/a1", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );
    const user = renderSection();
    await screen.findByText("file-a1.pdf");

    await user.click(
      screen.getByRole("button", { name: "Delete file-a1.pdf" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });
});
