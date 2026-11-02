import { render, screen, waitFor, within } from "@/test/utils";
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useState } from "react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { signInWith, signOut } from "@/test/auth";
import ItemsPage from "./ItemsPage";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function desktop(matches: boolean) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: matches && query === "(min-width: 1024px)",
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

const now = new Date().toISOString();
const row = (id: string, name: string) => ({
  id,
  name,
  quantity: 3,
  location_id: "1",
  created_at: now,
  updated_at: now,
});

/** The list endpoint, answering a long list and keeping every ask it got. */
function serveLongList(total = 120) {
  const asks: URLSearchParams[] = [];
  server.use(
    http.get("/api/v1/items", ({ request }) => {
      const params = new URL(request.url).searchParams;
      asks.push(params);
      const offset = Number(params.get("offset") ?? 0);
      return HttpResponse.json({
        items: [row(`r-${offset}`, `Row at ${offset}`), row("b", "Beta")],
        total,
      });
    }),
    http.get("/api/v1/items/aggregates", () =>
      HttpResponse.json({ count: total, total_weight: 0, total_value: 0 }),
    ),
    // A workspace that keeps dates, so the expiry chips are offered: the
    // statistics module says so, and only where it is on.
    http.get("/api/v1/modules/my", () =>
      HttpResponse.json(["core", "items", "locations", "categories", "stats"]),
    ),
    http.get("/api/v1/stats/overview", () =>
      HttpResponse.json({ total_items: total, tracks_expiry: true }),
    ),
  );
  return asks;
}

function renderWithHeader() {
  function Harness() {
    const [header, setHeader] = useState<PageHeaderData>({});
    return (
      <PageHeaderContext.Provider value={{ data: header, setHeader }}>
        <div data-testid="page-header">{header.actions}</div>
        <ItemsPage />
      </PageHeaderContext.Provider>
    );
  }
  return render(<Harness />);
}

/** The list's own asks — not the one-row probes that only count. */
const last = (asks: URLSearchParams[]) =>
  asks.filter((a) => a.get("limit") !== "1").at(-1)!;

/**
 * The list's own controls each change the question the page asks the API:
 * a sort that never reaches `sort_by`, a page arrow that does not move the
 * offset, an expiry chip that filters nothing. The list on screen would keep
 * answering the old question while the control says otherwise.
 */
describe("ItemsPage — the controls change what the list asks for", () => {
  beforeEach(() => {
    signInWith(["items:read", "items:write", "items:delete"]);
    desktop(true);
    mockNavigate.mockClear();
  });

  afterEach(() => signOut());

  it("asks for the chosen sort", async () => {
    const asks = serveLongList();
    const user = userEvent.setup();
    renderWithHeader();
    await screen.findAllByText("Beta");

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Sort" }),
      "expiry_date_asc",
    );

    await waitFor(() => {
      expect(last(asks).get("sort_by")).toBe("expiry_date");
      expect(last(asks).get("sort_order")).toBe("asc");
    });
  });

  it("moves the offset with the page arrows, the typed page and the page size", async () => {
    const asks = serveLongList();
    const user = userEvent.setup();
    renderWithHeader();
    await screen.findAllByText("Beta");
    const sizes = screen.getByRole("combobox", { name: /rows per page/i });
    const limit = Number((sizes as HTMLSelectElement).value);

    await user.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(last(asks).get("offset")).toBe(String(limit)));

    await user.click(screen.getByRole("button", { name: /previous/i }));
    await waitFor(() => expect(last(asks).get("offset")).toBe("0"));

    const page = screen.getByRole("spinbutton", { name: /page/i });
    await user.clear(page);
    await user.type(page, "2{Enter}");
    await waitFor(() => expect(last(asks).get("offset")).toBe(String(limit)));

    const other = Array.from((sizes as HTMLSelectElement).options)
      .map((o) => o.value)
      .find((v) => v !== String(limit))!;
    await user.selectOptions(sizes, other);
    await waitFor(() => expect(last(asks).get("limit")).toBe(other));
  });

  it("filters by expiry, expired and low stock through the chips", async () => {
    const asks = serveLongList();
    const user = userEvent.setup();
    renderWithHeader();
    await screen.findAllByText("Beta");

    await user.click(
      await screen.findByRole("button", { name: /only expiring soon/i }),
    );
    await waitFor(() => expect(last(asks).get("expiring_days")).not.toBeNull());

    await user.click(screen.getByRole("button", { name: /^expired/i }));
    await waitFor(() => expect(last(asks).get("only_expired")).toBe("true"));

    await user.click(screen.getByRole("button", { name: /running low/i }));
    await waitFor(() => expect(last(asks).get("only_low_stock")).toBe("true"));
  });

  it("selects every row and clears the selection from the bar", async () => {
    serveLongList(2);
    const user = userEvent.setup();
    renderWithHeader();
    await screen.findAllByText("Beta");

    const [selectAll] = screen.getAllByRole("checkbox");
    await user.click(selectAll!);
    const bar = await screen.findByRole("toolbar", { name: /selected/i });
    expect(bar).toHaveTextContent("2");

    await user.click(within(bar).getByRole("button", { name: /clear/i }));
    await waitFor(() =>
      expect(screen.queryByRole("toolbar", { name: /selected/i })).toBeNull(),
    );
  });
});

/**
 * The phone's header sheet: it has to close when asked and lead to the
 * categories register, the one place on the page it alone reaches.
 */
describe("ItemsPage — the phone's actions sheet", () => {
  beforeEach(() => {
    signInWith(["items:read", "items:write", "items:delete"]);
    desktop(false);
    mockNavigate.mockClear();
  });

  afterEach(() => signOut());

  it("leads to the categories and closes again", async () => {
    const user = userEvent.setup();
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);
    const header = screen.getByTestId("page-header");

    await user.click(within(header).getByRole("button", { name: /more/i }));
    const sheet = await screen.findByRole("dialog", { name: /more/i });
    await user.click(
      within(sheet).getByRole("button", { name: /categories/i }),
    );
    expect(mockNavigate).toHaveBeenCalledWith("/inventory/categories");

    await user.click(within(header).getByRole("button", { name: /more/i }));
    expect(
      await screen.findByRole("dialog", { name: /more/i }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /more/i })).toBeNull(),
    );
  });

  it("asks how much to remove from a card, sends it, and closes on cancel", async () => {
    let body: Record<string, unknown> | null = null;
    server.use(
      http.patch("/api/v1/items/:id/consume", async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...row("1", "Test Item"), quantity: 9 });
      }),
    );
    const user = userEvent.setup();
    renderWithHeader();
    await screen.findAllByText(/Test Item/i);

    await user.click(screen.getByRole("button", { name: "Remove 1 unit" }));
    let dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Remove from stock");
    await user.click(within(dialog).getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(body).toBeNull();

    await user.click(screen.getByRole("button", { name: "Remove 1 unit" }));
    dialog = await screen.findByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", { name: /^remove( 1)?$/i }),
    );
    await waitFor(() => expect(body).toMatchObject({ quantity: 1 }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  });
});
