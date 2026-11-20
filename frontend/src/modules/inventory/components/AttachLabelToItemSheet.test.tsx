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
              effective_expiry_date: "2020-03-01",
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

  it("prints the serial of a unit and numbers twins that still read the same", async () => {
    const stock = {
      label_code: null,
      location_id: "s1",
      quantity: "1.000",
    };
    server.use(
      http.get("/api/v1/items", () =>
        HttpResponse.json({
          items: [
            { ...stock, id: "i1", name: "QA Laptop", serial_number: "SN-001" },
            { ...stock, id: "i2", name: "QA Laptop", serial_number: "SN-002" },
            { ...stock, id: "iaaa111", name: "QA Cable" },
            { ...stock, id: "ibbb222", name: "QA Cable" },
            { ...stock, id: "icc3333", name: "QA Cord" },
          ],
          total: 5,
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
      target: { value: "QA" },
    });

    const laptops = await screen.findAllByRole("button", {
      name: /QA Laptop/,
    });
    expect(laptops[0]).toHaveTextContent("SN-001");
    expect(laptops[1]).toHaveTextContent("SN-002");
    // The serials already tell the laptops apart: no twin mark on them.
    expect(laptops[0]).not.toHaveTextContent("#");
    const cables = screen.getAllByRole("button", { name: /QA Cable/ });
    expect(cables[0]).toHaveTextContent("#aaa111");
    expect(cables[1]).toHaveTextContent("#bbb222");
    // A lone row carries no mark.
    expect(
      screen.getByRole("button", { name: /QA Cord/ }),
    ).not.toHaveTextContent("#");
  });
});
