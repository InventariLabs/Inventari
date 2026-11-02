import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, fireEvent, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { LocationContentsSheet } from "./LocationContentsSheet";
import { onePage } from "@/test/mocks/page";

let canWrite = true;
let enabled = ["stock_takes"];
vi.mock("@/hooks/useCanWrite", () => ({ useCanWrite: () => canWrite }));
vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({ isModuleEnabled: (m: string) => enabled.includes(m) }),
}));

const navigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => navigate };
});

const row = (over: Record<string, unknown>) => ({
  id: "q",
  product_template_id: "p",
  location_id: "rack",
  quantity: "1.000",
  reserved_quantity: "0",
  available_quantity: "1.000",
  product_name: "Flour",
  uom_symbol: "kg",
  location_name: "Rack",
  lot_name: null,
  lot_status: null,
  expiry_date: null,
  ...over,
});

const answer = (items: unknown[], total = items.length) => {
  let asked = "";
  server.use(
    http.get("/api/v1/stock-quants", ({ request }) => {
      asked = new URL(request.url).searchParams.get("location_id") ?? "";
      return HttpResponse.json({ items, total, offset: 0, limit: 100 });
    }),
    // The places the rows stand in, named by id with the way to them.
    http.get("/api/v1/locations", ({ request }) => {
      const ids = new URL(request.url).searchParams.getAll("ids");
      const places = [
        { id: "rack", name: "Rack", parent_id: null, full_path: "Rack" },
        {
          id: "shelf",
          name: "Shelf 2",
          parent_id: "rack",
          full_path: "Rack → Shelf 2",
        },
      ].filter((place) => ids.length === 0 || ids.includes(place.id));
      return HttpResponse.json(onePage(places));
    }),
  );
  return () => asked;
};

const show = (
  onUseAsContext?: () => void,
  onClose = vi.fn(),
  offerLabel = false,
) => {
  render(
    <LocationContentsSheet
      location={{ id: "rack", name: "Rack" }}
      onClose={onClose}
      onUseAsContext={onUseAsContext}
      offerLabel={offerLabel}
    />,
  );
  return onClose;
};

beforeEach(() => {
  canWrite = true;
  enabled = ["stock_takes"];
  navigate.mockReset();
});

describe("LocationContentsSheet", () => {
  it("lists what stands on the shelves below, with quantity, lot and date", async () => {
    const asked = answer([
      row({ id: "a", product_name: "Rye flour", quantity: "4.000" }),
      row({
        id: "b",
        location_id: "shelf",
        location_name: "Shelf 2",
        product_name: "Milk",
        uom_symbol: "l",
        quantity: "2.000",
        lot_name: "L-7",
        expiry_date: "2031-05-01",
      }),
    ]);
    show();

    expect(await screen.findByText("Rye flour")).toBeInTheDocument();
    expect(asked()).toBe("rack");
    const milk = screen.getByText("Milk").closest("li")!;
    await waitFor(() => expect(milk).toHaveTextContent("Rack → Shelf 2"));
    expect(milk).toHaveTextContent("L-7");
    expect(milk).toHaveTextContent(/Use by/);
    expect(milk).toHaveTextContent("2 l");
  });

  it("says plainly when nothing is stored there", async () => {
    answer([]);
    show();

    expect(await screen.findByText(/Nothing is stored here/)).toBeVisible();
  });

  it("says how many lines it left out", async () => {
    answer([row({})], 150);
    show();

    expect(await screen.findByText(/149 more lines not shown/)).toBeVisible();
  });

  it("makes the place the scan context and closes", async () => {
    answer([row({})]);
    const useAsContext = vi.fn();
    const onClose = show(useAsContext);

    fireEvent.click(
      await screen.findByRole("button", { name: "Use as scan context" }),
    );

    expect(useAsContext).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("reprints the shelf's own label in one action where the screen offers it", async () => {
    answer([row({})]);
    const previewed: unknown[] = [];
    server.use(
      http.post("/api/v1/printing/location-labels/png", async ({ request }) => {
        previewed.push(await request.json());
        return new HttpResponse(new Uint8Array([0x89, 0x50]), {
          headers: { "Content-Type": "image/png" },
        });
      }),
      http.get("/api/v1/printing/agents", () => HttpResponse.json([])),
    );
    show(undefined, vi.fn(), true);

    fireEvent.click(await screen.findByRole("button", { name: "Print label" }));

    await waitFor(() =>
      expect(previewed.at(-1)).toMatchObject({ location_ids: ["rack"] }),
    );
  });

  it("offers no label button unless the screen asks for it", async () => {
    answer([row({})]);
    show();

    await screen.findByText("Flour");
    expect(
      screen.queryByRole("button", { name: "Print label" }),
    ).not.toBeInTheDocument();
  });

  it("offers no scan context where the screen keeps none", async () => {
    answer([row({})]);
    show();

    await screen.findByText("Flour");
    expect(
      screen.queryByRole("button", { name: "Use as scan context" }),
    ).not.toBeInTheDocument();
  });

  it("opens the location, starts a count there and moves it", async () => {
    answer([row({})]);
    show();
    await screen.findByText("Flour");

    fireEvent.click(screen.getByRole("button", { name: "Open location" }));
    expect(navigate).toHaveBeenLastCalledWith("/inventory/locations/rack");

    fireEvent.click(
      await screen.findByRole("button", { name: "Start a stock take" }),
    );
    expect(navigate).toHaveBeenLastCalledWith(
      "/inventory/stock-takes?new=rack",
    );

    fireEvent.click(screen.getByRole("button", { name: "Move" }));
    // Move is a promise about one field, so the address says which one the
    // edit sheet should land on.
    expect(navigate).toHaveBeenLastCalledWith(
      "/inventory/locations/rack?configure=true&focus=move",
    );
  });

  it("offers a reader only the actions that change nothing", async () => {
    canWrite = false;
    answer([row({})]);
    show();
    await screen.findByText("Flour");

    expect(
      screen.getByRole("button", { name: "Open location" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Start a stock take" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Move" }),
    ).not.toBeInTheDocument();
  });

  it("does not offer a count on a place a module owns, which no stock take can pick", async () => {
    answer([row({})]);
    // The stock-flow scope keeps the module's own place out.
    server.use(
      http.get("/api/v1/locations", ({ request }) => {
        const params = new URL(request.url).searchParams;
        const places =
          params.get("exclude_module_contexts") === "true"
            ? []
            : [
                {
                  id: "rack",
                  name: "Rack",
                  parent_id: null,
                  full_path: "Rack",
                },
              ];
        return HttpResponse.json(onePage(places));
      }),
    );
    show();
    await screen.findByText("Flour");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Open location" }),
      ).toBeInTheDocument(),
    );

    expect(
      screen.queryByRole("button", { name: "Start a stock take" }),
    ).not.toBeInTheDocument();
  });

  it("does not offer a count when the stock takes module is off", async () => {
    enabled = [];
    answer([row({})]);
    show();
    await screen.findByText("Flour");

    expect(
      screen.queryByRole("button", { name: "Start a stock take" }),
    ).not.toBeInTheDocument();
  });
});
