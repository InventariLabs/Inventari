import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import type { Item } from "@/types";
import { AttachLabelToExistingItemSheet } from "./AttachLabelToExistingItemSheet";
import ItemLabelAttachSlot from "./ItemLabelAttachSlot";

let canWrite = true;
vi.mock("@/hooks/useCanWrite", () => ({ useCanWrite: () => canWrite }));

const wrap = (ui: React.ReactElement) =>
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      {ui}
    </QueryClientProvider>,
  );

describe("AttachLabelToExistingItemSheet — a product page, a free label", () => {
  it("offers the free pool labels and binds the chosen one to the product", async () => {
    let itemId: string | null = null;
    let code = "";
    server.use(
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json({
          items: [{ id: "l1", short_code: "STM-0007", description: null }],
          total: 1,
        }),
      ),
      http.post(
        "/api/v1/labels/pool/:code/assign-item",
        ({ params, request }) => {
          code = String(params.code);
          itemId = new URL(request.url).searchParams.get("item_id");
          return HttpResponse.json({ id: "l1", short_code: params.code });
        },
      ),
    );
    const onAttached = vi.fn();
    wrap(
      <AttachLabelToExistingItemSheet
        item={{ id: "i9", name: "Flour" }}
        onClose={() => {}}
        onAttached={onAttached}
      />,
    );

    expect(screen.getByRole("button", { name: "Attach label" })).toBeDisabled();

    fireEvent.click(screen.getByText("No label assigned"));
    fireEvent.click(await screen.findByText("STM-0007"));
    fireEvent.click(screen.getByRole("button", { name: "Attach label" }));

    await waitFor(() => expect(onAttached).toHaveBeenCalled());
    expect(code).toBe("STM-0007");
    expect(itemId).toBe("i9");
  });
});

describe("ItemLabelAttachSlot — the product page's door", () => {
  const item = { id: "i9", name: "Flour", label_code: null } as Item;

  it("offers the attach button on a product with no label", () => {
    canWrite = true;
    wrap(<ItemLabelAttachSlot data={{ item }} />);
    expect(
      screen.getByRole("button", { name: "Attach a label" }),
    ).toBeInTheDocument();
  });

  it("stays silent on a product that already has a label", () => {
    canWrite = true;
    wrap(
      <ItemLabelAttachSlot data={{ item: { ...item, label_code: "STM-1" } }} />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("stays silent for a reader who cannot write", () => {
    canWrite = false;
    wrap(<ItemLabelAttachSlot data={{ item }} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("opens the attach sheet for this product, and Cancel puts it away", async () => {
    canWrite = true;
    wrap(<ItemLabelAttachSlot data={{ item }} />);

    fireEvent.click(screen.getByRole("button", { name: "Attach a label" }));
    expect(
      await screen.findByText(/Pick a free label/i, { exact: false }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Attach label" })).toBeNull(),
    );
  });

  it("puts the sheet away once the label is attached", async () => {
    canWrite = true;
    server.use(
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json({
          items: [{ id: "l1", short_code: "STM-0007", description: null }],
          total: 1,
        }),
      ),
      http.post("/api/v1/labels/pool/:code/assign-item", ({ params }) =>
        HttpResponse.json({ id: "l1", short_code: params.code }),
      ),
    );
    wrap(<ItemLabelAttachSlot data={{ item }} />);

    fireEvent.click(screen.getByRole("button", { name: "Attach a label" }));
    fireEvent.click(await screen.findByText("No label assigned"));
    fireEvent.click(await screen.findByText("STM-0007"));
    fireEvent.click(screen.getByRole("button", { name: "Attach label" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Attach label" })).toBeNull(),
    );
  });
});
