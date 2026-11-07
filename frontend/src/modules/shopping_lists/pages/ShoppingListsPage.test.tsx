import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { BrowserRouter, MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ShoppingListsPage from "./ShoppingListsPage";
import { useAuthStore } from "@/store/authStore";
import i18n from "@/i18n/config";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { useShoppingLists } from "../hooks/useShoppingLists";

vi.mock("../hooks/useShoppingLists", () => ({
  useShoppingLists: vi.fn(),
  useShoppingListStats: vi.fn(() => ({})),
  useDeleteShoppingList: vi.fn(() => ({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  })),
  useUpdateShoppingList: vi.fn(() => ({
    mutateAsync: vi.fn().mockResolvedValue(undefined),
    isPending: false,
  })),
}));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
    },
  },
});

describe("ShoppingListsPage", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await i18n.changeLanguage("en");

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
        // Creating, renaming and deleting a list are writes.
        permissions: ["shopping_lists:read", "shopping_lists:write"],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  it("should render loading spinner initially", () => {
    vi.mocked(useShoppingLists).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as unknown as ReturnType<typeof useShoppingLists>);

    const { container } = render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("should render empty state when no lists exist", async () => {
    vi.mocked(useShoppingLists).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useShoppingLists>);

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    const createBtn = await screen.findByRole("button", { name: /New list/i });
    expect(createBtn).toBeInTheDocument();
  });

  it("does not tell a reader to create a list they cannot create", async () => {
    useAuthStore.setState({
      user: {
        ...useAuthStore.getState().user!,
        permissions: ["shopping_lists:read"],
      },
    });
    vi.mocked(useShoppingLists).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useShoppingLists>);

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    expect(
      await screen.findByText(/will appear here once someone creates them/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/create your first/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /New list/i }),
    ).not.toBeInTheDocument();
  });

  it("should render shopping lists when data exists", async () => {
    const mockLists = [
      {
        id: "list-1",
        organization_id: "hh-1",
        name: "Biedronka Shopping",
        created_by: "user-1",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ];

    vi.mocked(useShoppingLists).mockReturnValue({
      data: mockLists,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useShoppingLists>);

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await waitFor(() => {
      expect(screen.getByText(/Biedronka Shopping/i)).toBeInTheDocument();
    });
  });

  it("should register create new list button in header", async () => {
    vi.mocked(useShoppingLists).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useShoppingLists>);

    const mockSetHeader = vi.fn();

    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await waitFor(() => {
      expect(mockSetHeader).toHaveBeenCalledWith(
        expect.objectContaining({ actions: expect.anything() }),
      );
    });
  });

  it("should show the reason the server gave on fetch failure", async () => {
    vi.mocked(useShoppingLists).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: {
        isAxiosError: true,
        response: { data: { detail: "Your session ended" } },
      },
    } as unknown as ReturnType<typeof useShoppingLists>);

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Your session ended")).toBeInTheDocument();
    });
  });

  it("should not show the HTTP library's own sentence when there is no reason", async () => {
    // axios names a failure "Request failed with status code 500"; that is a
    // library string, not a message anybody wrote for a reader.
    vi.mocked(useShoppingLists).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("Request failed with status code 500"),
    } as unknown as ReturnType<typeof useShoppingLists>);

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await waitFor(() => {
      expect(
        screen.getByText("Could not load your shopping lists"),
      ).toBeInTheDocument();
    });
    expect(screen.queryByText(/status code 500/)).not.toBeInTheDocument();
  });

  it("should navigate to list detail when clicking on list", async () => {
    const mockLists = [
      {
        id: "list-1",
        organization_id: "hh-1",
        name: "Biedronka Shopping",
        created_by: "user-1",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ];

    vi.mocked(useShoppingLists).mockReturnValue({
      data: mockLists,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useShoppingLists>);

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <Routes>
              <Route path="/" element={<ShoppingListsPage />} />
              <Route path="/shopping-lists/list-1" element={<p>The list</p>} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("link", { name: /Biedronka Shopping/i }),
    );

    expect(await screen.findByText("The list")).toBeInTheDocument();
  });

  it("should open create list modal when clicking create button", async () => {
    vi.mocked(useShoppingLists).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useShoppingLists>);

    const user = userEvent.setup();

    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    const createBtn = await screen.findByRole("button", { name: /New list/i });
    await user.click(createBtn);

    expect(
      await screen.findByText(/New shopping list|Nowa lista zakupów/i),
    ).toBeInTheDocument();
  });

  it("asks for one new list everywhere — the empty state uses the header's word", async () => {
    // Both controls open the same modal, so they carry the same accessible
    // name (§14.4): the empty state used to say "Create" where the header
    // said "New list".
    vi.mocked(useShoppingLists).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useShoppingLists>);

    const mockSetHeader = vi.fn();

    render(
      <PageHeaderContext.Provider
        value={{ data: {}, setHeader: mockSetHeader }}
      >
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <ShoppingListsPage />
          </BrowserRouter>
        </QueryClientProvider>
      </PageHeaderContext.Provider>,
    );

    await screen.findByRole("button", { name: "New list" });

    // The header's button is registered, not rendered — render it beside the
    // empty state's own button so both names are compared in one tree.
    const calls = mockSetHeader.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    render(calls[calls.length - 1][0].actions);

    expect(screen.getAllByRole("button", { name: "New list" })).toHaveLength(2);
  });
});
