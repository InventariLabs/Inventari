import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { AttachLabelToItemSheet } from "./AttachLabelToItemSheet";

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

describe("AttachLabelToItemSheet — a scanned free label, a product that exists", () => {
  let assigned: { code: string; itemId: string | null } | undefined;

  beforeEach(() => {
    assigned = undefined;
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({
          items: [
            { id: "i1", name: "Rice", label_code: null },
            { id: "i2", name: "Rice (stickered)", label_code: "STM-OLD" },
          ],
          total: 2,
        }),
      ),
      http.get("/api/v1/locations", () =>
        HttpResponse.json({
          items: [
            { id: "s1", name: "Main Warehouse", full_path: "Main Warehouse" },
            {
              id: "s2",
              name: "Quarantine",
              full_path: "Main Warehouse › Quarantine",
            },
          ],
          total: 2,
          has_more: false,
        }),
      ),
      http.post(
        "/api/v1/labels/pool/:code/assign-item",
        ({ params, request }) => {
          assigned = {
            code: String(params.code),
            itemId: new URL(request.url).searchParams.get("item_id"),
          };
          return HttpResponse.json({ id: "l1", short_code: params.code });
        },
      ),
    );
  });

  it("binds the label to the picked product and leaves out products that already carry one", async () => {
    const onAttached = vi.fn();
    wrap(
      <AttachLabelToItemSheet
        labelCode="STM-0001"
        onClose={() => {}}
        onAttached={onAttached}
      />,
    );

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Rice" },
    });

    const row = await screen.findByRole("button", { name: "Rice" });
    expect(screen.queryByText("Rice (stickered)")).not.toBeInTheDocument();

    fireEvent.click(row);

    await waitFor(() => expect(onAttached).toHaveBeenCalled());
    expect(assigned).toEqual({ code: "STM-0001", itemId: "i1" });
  });

  it("tells the stock rows of one product apart by where each stands", async () => {
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({
          items: [
            {
              id: "i1",
              name: "QA Product",
              label_code: null,
              location_id: "s1",
              quantity: "6.000",
            },
            {
              id: "i2",
              name: "QA Product",
              label_code: null,
              location_id: "s2",
              quantity: "4.000",
              effective_expiry_date: "2027-03-01",
            },
          ],
          total: 2,
        }),
      ),
    );
    wrap(
      <AttachLabelToItemSheet
        labelCode="STM-0001"
        onClose={() => {}}
        onAttached={() => {}}
      />,
    );

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "QA Prod" },
    });

    const rows = await screen.findAllByRole("button", { name: /QA Product/ });
    expect(rows).toHaveLength(2);
    await waitFor(() => expect(rows[0]).toHaveTextContent("Main Warehouse"));
    expect(rows[0]).not.toHaveTextContent("Quarantine");
    expect(rows[1]).toHaveTextContent("Main Warehouse › Quarantine");
    expect(rows[1]).toHaveTextContent("expires");
    expect(rows[1]).toHaveTextContent("4");
  });
});
