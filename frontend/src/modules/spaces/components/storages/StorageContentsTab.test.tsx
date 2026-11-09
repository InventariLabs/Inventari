import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";

import { StorageContentsTab } from "./StorageContentsTab";

function child(n: number) {
  return {
    id: `bin-${n}`,
    name: `Bin ${n}`,
    short_code: `B${n}`,
    location_type: { name: "Bin" },
    direct_children_count: 0,
    subtree_items_count: n,
  };
}

let requests: URLSearchParams[];

function serveChildren(total: number, count = Math.min(total, 2)) {
  server.use(
    http.get("/api/v1/locations", ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      return HttpResponse.json({
        items: Array.from({ length: count }, (_, i) => child(i + 1)),
        total,
        limit: 50,
        offset: Number(params.get("offset") ?? 0),
        has_more: total > count,
      });
    }),
  );
}

beforeEach(() => {
  requests = [];
});

function renderTab(
  overrides: Partial<Parameters<typeof StorageContentsTab>[0]> = {},
) {
  const props = {
    parent: { id: "rack-1", items_count: 4 },
    excludeModuleContexts: false,
    canWrite: true,
    onSelect: vi.fn(),
    onMove: vi.fn(),
    onShowProducts: vi.fn(),
    ...overrides,
  };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <StorageContentsTab {...props} />
    </QueryClientProvider>,
  );
  return props;
}

/**
 * The contents table is how the reader walks down the tree and picks
 * locations to move. A row that opens the wrong location, a move that
 * carries rows nobody ticked, or a leaf shown as an empty table all fail
 * here.
 */
describe("StorageContentsTab", () => {
  it("asks for the children of the selected location, and opens the row that is pressed", async () => {
    serveChildren(2);
    const props = renderTab();

    await screen.findAllByText("Bin 2");
    expect(requests[0].get("parent_id")).toBe("rack-1");

    await userEvent.click(screen.getAllByRole("button", { name: "Bin 2" })[0]);
    expect(props.onSelect).toHaveBeenCalledWith("bin-2");
  });

  it("moves exactly the ticked rows, and clearing the selection hides the action", async () => {
    serveChildren(2);
    const props = renderTab();
    await screen.findAllByText("Bin 1");

    await userEvent.click(
      screen.getAllByRole("checkbox", { name: "Select Bin 1" })[0],
    );
    await userEvent.click(
      screen.getAllByRole("checkbox", { name: "Select Bin 2" })[0],
    );
    expect(screen.getByText("2 locations selected")).toBeInTheDocument();
    await userEvent.click(
      screen.getAllByRole("checkbox", { name: "Select Bin 2" })[0],
    );
    expect(screen.getByText("1 location selected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Move to…" }));
    expect(props.onMove).toHaveBeenCalledWith(["bin-1"]);

    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText(/selected/)).not.toBeInTheDocument();
  });

  it("offers no selection to a reader who cannot write", async () => {
    serveChildren(2);
    renderTab({ canWrite: false });
    await screen.findAllByText("Bin 1");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("points a leaf at its products instead of an empty table", async () => {
    serveChildren(0, 0);
    const props = renderTab();

    expect(
      await screen.findByText("Nothing inside this location"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Its 4 records are on the Products tab."),
    ).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Show products" }),
    );
    expect(props.onShowProducts).toHaveBeenCalledTimes(1);
  });

  it("offers no button to an empty products tab when the location holds nothing", async () => {
    serveChildren(0, 0);
    renderTab({ parent: { id: "rack-1", items_count: 0 } });

    expect(
      await screen.findByText("Nothing inside this location"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("It holds no records and has no locations inside."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0 records/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Show products" }),
    ).not.toBeInTheDocument();
  });

  it("pages through more than fifty children", async () => {
    serveChildren(120);
    renderTab();
    await screen.findAllByText("Bin 1");

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() =>
      expect(requests[requests.length - 1].get("offset")).toBe("50"),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Previous page" }),
    );
    await waitFor(() =>
      expect(requests[requests.length - 1].get("offset")).toBe("0"),
    );
  });

  it("offers a retry when the children could not be read", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/locations", () => {
        calls++;
        return calls === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json({
              items: [child(1)],
              total: 1,
              limit: 50,
              offset: 0,
              has_more: false,
            });
      }),
    );
    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: /Try again|Retry/ }),
    );
    expect((await screen.findAllByText("Bin 1")).length).toBeGreaterThan(0);
  });
});
