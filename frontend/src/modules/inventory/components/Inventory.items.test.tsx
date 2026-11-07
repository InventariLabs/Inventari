import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { signInWith, signOut } from "@/test/auth";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import ItemsEmptyState from "./items/ItemsEmptyState";
import ItemsPagination from "./items/ItemsPagination";
import ItemsBulkActionBar from "./items/ItemsBulkActionBar";

// Deleting in bulk is `items:delete` on the API; the bar asks before
// offering it.
beforeEach(() => signInWith(["items:read", "items:write", "items:delete"]));
afterEach(signOut);

vi.mock("@/lib/moduleRegistry", () => ({
  moduleRegistry: {
    getBulkActions: vi.fn(() => []),
  },
}));

const noop = vi.fn();

// The empty list asks the catalogue whether products wait without stock, so
// it needs a query client beside the router.
function Shell({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

// ─── ItemsEmptyState ─────────────────────────────────────────────────────────

describe("ItemsEmptyState", () => {
  it("renders add-first text when no filters active", () => {
    render(
      <Shell>
        <ItemsEmptyState hasFilters={false} />
      </Shell>,
    );
    expect(screen.getByText("No products")).toBeInTheDocument();
    expect(
      screen.getByText(
        /^Add your first product to a location\. Export unlocks once there is a product\.$/,
      ),
    ).toBeInTheDocument();
  });

  it("under an active filter says nothing matches, and offers to clear it", () => {
    // Two products and one chip on gave "No products / Add your first
    // product": the answer a filter owes the reader is that the filter found
    // nothing, and the way back to the rows the account plainly has.
    const onClearFilters = vi.fn();
    render(
      <Shell>
        <ItemsEmptyState hasFilters={true} onClearFilters={onClearFilters} />
      </Shell>,
    );
    expect(screen.getByText("No matching products")).toBeInTheDocument();
    expect(screen.getByText("Try changing filters")).toBeInTheDocument();
    expect(screen.queryByText("No products")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/^Add your first product to a location\./),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /clear filters/i }));
    expect(onClearFilters).toHaveBeenCalled();
  });

  it("keeps the add-first offer off a filtered list without a way back", () => {
    // The clearing callback is the only thing the action changes; the claim
    // that the account should add a product is wrong either way.
    render(
      <Shell>
        <ItemsEmptyState hasFilters={true} />
      </Shell>,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/^Add your first product to a location\./),
    ).not.toBeInTheDocument();
  });

  it("renders link to /inventory/items/add", () => {
    render(
      <Shell>
        <ItemsEmptyState hasFilters={false} />
      </Shell>,
    );
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/inventory/items/add");
  });

  it("renders search-specific message and a clear button when search term is set", () => {
    const onClear = vi.fn();
    render(
      <Shell>
        <ItemsEmptyState
          hasFilters={true}
          searchTerm="milk"
          onClearSearch={onClear}
        />
      </Shell>,
    );
    expect(screen.getByText(/milk/)).toBeInTheDocument();
    const clearBtn = screen.getByRole("button", { name: /clear search/i });
    expect(clearBtn).toBeInTheDocument();
    fireEvent.click(clearBtn);
    expect(onClear).toHaveBeenCalled();
  });

  it("a search that matches only a definition says the product exists", async () => {
    // Created inside a BOM, the product has no stock, so the list cannot hold
    // it — and "No results" over a name the reader just made is a false answer.
    vi.spyOn(productTemplatesApi, "search").mockResolvedValue([
      { id: "t1", name: "Wosk sojowy" },
    ] as never);
    render(
      <Shell>
        <ItemsEmptyState
          hasFilters={true}
          searchTerm="sojowy"
          onClearSearch={vi.fn()}
        />
      </Shell>,
    );
    expect(
      await screen.findByText(/“Wosk sojowy” is not in a location yet/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^No results for/)).not.toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/inventory/items/add",
    );
  });

  it("names the hidden module data instead of an empty warehouse", () => {
    // "No products" over rows that plainly exist is how an organization
    // concludes the app lost its data — the answer it owes the reader is
    // where the rows went and which switch brings them back.
    render(
      <Shell>
        <ItemsEmptyState hasFilters={false} hiddenCount={2} />
      </Shell>,
    );
    expect(screen.getByText("Some products are hidden")).toBeInTheDocument();
    expect(screen.queryByText("No products")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /add/i }),
    ).not.toBeInTheDocument();
  });

  it("keeps the narrowed answer when filters are active", () => {
    // "No results" for a search the reader typed is a different answer than
    // the module filter's — the hint must not overwrite it.
    render(
      <Shell>
        <ItemsEmptyState hasFilters={true} hiddenCount={2} />
      </Shell>,
    );
    expect(screen.getByText("Try changing filters")).toBeInTheDocument();
    expect(
      screen.queryByText("Some products are hidden"),
    ).not.toBeInTheDocument();
  });
});

// ─── ItemsPagination ──────────────────────────────────────────────────────────

describe("ItemsPagination", () => {
  const defaultProps = {
    skip: 0,
    limit: 20,
    total: 60,
    onPrev: noop,
    onNext: noop,
  };

  it("renders page 1/1 and disables both buttons when total <= limit", () => {
    render(
      <ItemsPagination
        skip={0}
        limit={20}
        total={10}
        onPrev={noop}
        onNext={noop}
      />,
    );
    expect(screen.getByText("1 / 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
  });

  it("renders null when total is zero", () => {
    const { container } = render(
      <ItemsPagination
        skip={0}
        limit={20}
        total={0}
        onPrev={noop}
        onNext={noop}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders page count when total > limit", () => {
    render(<ItemsPagination {...defaultProps} />);
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("disables prev button on first page", () => {
    render(<ItemsPagination {...defaultProps} />);
    const prevBtn = screen.getByRole("button", {
      name: /previous/i,
    });
    expect(prevBtn).toBeDisabled();
  });

  it("calls onNext when next button clicked", () => {
    const onNext = vi.fn();
    render(<ItemsPagination {...defaultProps} onNext={onNext} />);
    const nextBtn = screen.getByRole("button", { name: /next/i });
    fireEvent.click(nextBtn);
    expect(onNext).toHaveBeenCalled();
  });

  it("disables next button on last page", () => {
    render(
      <ItemsPagination
        skip={40}
        limit={20}
        total={60}
        onPrev={noop}
        onNext={noop}
      />,
    );
    const nextBtn = screen.getByRole("button", { name: /next/i });
    expect(nextBtn).toBeDisabled();
  });
});

// ─── ItemsBulkActionBar ───────────────────────────────────────────────────────

describe("ItemsBulkActionBar", () => {
  const defaultProps = {
    selectedIds: ["a", "b"],
    onClearSelection: noop,
    onBulkEdit: noop,
    onBulkDelete: noop,
    isPendingDelete: false,
    enabledModules: [],
  };

  it("renders null when selectedIds is empty", () => {
    const { container } = render(
      <ItemsBulkActionBar {...defaultProps} selectedIds={[]} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows selected count", () => {
    render(<ItemsBulkActionBar {...defaultProps} />);
    // The count says what it counts now — a bare "2" beside a row of actions
    // left the reader to guess whether it was rows, pages or minutes.
    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("calls onClearSelection when X button clicked", () => {
    const onClearSelection = vi.fn();
    render(
      <ItemsBulkActionBar
        {...defaultProps}
        onClearSelection={onClearSelection}
      />,
    );
    const clearBtn = screen.getByRole("button", { name: /clear/i });
    fireEvent.click(clearBtn);
    expect(onClearSelection).toHaveBeenCalled();
  });

  it("shows edit button", () => {
    render(<ItemsBulkActionBar {...defaultProps} />);
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
  });

  it("shows delete button disabled when isPendingDelete=true", () => {
    render(<ItemsBulkActionBar {...defaultProps} isPendingDelete={true} />);
    const deleteBtn = screen.getByRole("button", { name: /delete/i });
    expect(deleteBtn).toBeDisabled();
  });

  it("hides bulk Delete from a writer without items:delete, and keeps the bar", () => {
    signInWith(["items:read", "items:write"]);
    render(<ItemsBulkActionBar {...defaultProps} />);
    // Edit is `items:write`; deleting is the narrower `items:delete`.
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
  });
});
