import { useState, type ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import ShoppingListDetailPage from "./ShoppingListDetailPage";
import { useAuthStore } from "@/store/authStore";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  useShoppingListDetail,
  useToggleShoppingItem,
} from "../hooks/useShoppingLists";

function ShellWrapper({ children }: { children: ReactNode }) {
  const [headerData, setHeaderData] = useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {headerData.title && <h1>{headerData.title}</h1>}
      {headerData.subtitle && <p>{headerData.subtitle}</p>}
      {headerData.actions}
      {children}
    </PageHeaderContext.Provider>
  );
}

vi.mock("../hooks/useShoppingLists", () => ({
  useShoppingListDetail: vi.fn(),
  useToggleShoppingItem: vi.fn(() => ({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  })),
  useConvertToPO: vi.fn(() => ({
    mutateAsync: vi.fn().mockResolvedValue({
      po_id: "po-1",
      po_number: "PO/2026/0001",
      converted_count: 1,
      skipped_count: 0,
      skipped_items: [],
    }),
    isPending: false,
  })),
  useClearPurchasedItems: vi.fn(() => ({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  })),
  useDeleteShoppingItem: vi.fn(() => ({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  })),
}));

const makeQueryResult = <T = unknown,>(
  data: T,
  isLoading = false,
  error: unknown = null,
) =>
  ({
    data,
    isLoading,
    error,
    isError: !!error,
    isSuccess: !isLoading && !error,
    isPending: isLoading,
    status: error ? "error" : isLoading ? "pending" : "success",
    fetchStatus: "idle",
    isFetching: false,
    isPaused: false,
    isLoadingError: false,
    isRefetchError: false,
    isPlaceholderData: false,
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    failureCount: 0,
    failureReason: null,
    errorUpdateCount: 0,
    isFetched: true,
    isFetchedAfterMount: true,
    isInitialLoading: false,
    isRefetching: false,
    isStale: false,
    refetch: vi.fn(),
  }) as unknown as ReturnType<typeof useShoppingListDetail>;

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

describe("ShoppingListDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_active: true,
        is_superuser: false,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        // Ticking an item off and clearing the purchased ones are writes.
        permissions: ["shopping_lists:read", "shopping_lists:write"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  const renderWithRouter = (id: string) => {
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[`/shopping-lists/${id}`]}>
          <ModulesProvider>
            <Routes>
              <Route
                path="/shopping-lists/:id"
                element={
                  <ShellWrapper>
                    <ShoppingListDetailPage />
                  </ShellWrapper>
                }
              />
            </Routes>
          </ModulesProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  };

  it("should render list details and items", async () => {
    const mockList = {
      id: "list-1",
      name: "Weekly Shopping",
      items: [
        {
          id: "item-1",
          name: "Milk",
          quantity: 2,
          unit: "pcs",
          is_purchased: false,
          priority: 0,
          source: "manual",
        },
        {
          id: "item-2",
          name: "Bread",
          quantity: 1,
          unit: "pcs",
          is_purchased: true,
          priority: 0,
          source: "manual",
        },
      ],
    };

    vi.mocked(useShoppingListDetail).mockReturnValue(makeQueryResult(mockList));

    renderWithRouter("list-1");

    expect(await screen.findByText(/Weekly Shopping/i)).toBeInTheDocument();
    expect(screen.getByText(/Milk/i)).toBeInTheDocument();
    expect(screen.getByText(/Bread/i)).toBeInTheDocument();

    expect(screen.getByText(/1 (do kupna|to buy)/i)).toBeInTheDocument();
    expect(screen.getByText(/1 (kupione|purchased)/i)).toBeInTheDocument();
  });

  it("should show empty state message", async () => {
    vi.mocked(useShoppingListDetail).mockReturnValue(
      makeQueryResult({
        id: "list-1",
        name: "Empty List",
        organization_id: "org-1",
        created_by: "user-1",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        items: [],
      }),
    );

    renderWithRouter("list-1");

    expect(
      await screen.findByText(/Lista jest pusta|List is empty/i),
    ).toBeInTheDocument();
    // The empty state used to send the reader to auto-suggestions, which
    // this screen does not have — the door it names must be one that is on
    // the screen ("Add item").
    expect(screen.queryByText(/auto-sugestii|auto-suggestions/i)).toBeNull();
    expect(
      screen.getAllByRole("button", { name: /dodaj|add/i }).length,
    ).toBeGreaterThan(0);
  });

  it("should toggle item purchased status", async () => {
    const mockList = {
      id: "list-1",
      name: "List",
      items: [
        {
          id: "item-1",
          name: "Milk",
          quantity: 1,
          unit: "pcs",
          is_purchased: false,
          priority: 0,
          source: "manual",
        },
      ],
    };

    const mockMutateAsync = vi.fn().mockResolvedValue(undefined);
    vi.mocked(useShoppingListDetail).mockReturnValue(makeQueryResult(mockList));
    vi.mocked(useToggleShoppingItem).mockReturnValue({
      mutateAsync: mockMutateAsync,
      isPending: false,
    } as unknown as ReturnType<typeof useToggleShoppingItem>);

    renderWithRouter("list-1");

    const item = await screen.findByText(/Milk/i);
    fireEvent.click(item);

    expect(mockMutateAsync).toHaveBeenCalledWith({
      itemId: "item-1",
      currentStatus: false,
    });
  });
});
