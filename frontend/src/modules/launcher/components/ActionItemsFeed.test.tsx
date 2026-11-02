import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Bell } from "lucide-react";
import { ActionItemsFeed } from "./ActionItemsFeed";
import { ModulesProvider } from "@/contexts/ModulesContext";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { ActionItem, FrontendModule } from "@/lib/moduleRegistry";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

function makeModule(
  name: string,
  hook: FrontendModule["useActionItems"],
): FrontendModule {
  return {
    name,
    routes: [],
    useActionItems: hook,
  };
}

function renderFeed() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ModulesProvider>
        <MemoryRouter>
          <ActionItemsFeed />
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

describe("ActionItemsFeed", () => {
  beforeEach(() => {
    moduleRegistry.getActionItemProviders = vi.fn(() => []);
  });

  it("renders nothing when no module provides action items", () => {
    renderFeed();
    expect(screen.queryByTestId("action-items-feed")).not.toBeInTheDocument();
  });

  it("renders items from a registered module hook", async () => {
    const sampleItems: ActionItem[] = [
      {
        id: "approve-1",
        labelKey: "approvals:action.reviewPending",
        icon: Bell,
        severity: "warning",
        linkTo: "/approvals",
        count: 3,
      },
    ];
    moduleRegistry.register(makeModule("with-actions", () => sampleItems));
    moduleRegistry.getActionItemProviders = vi.fn(() => [
      { moduleName: "with-actions", hook: () => sampleItems },
    ]);

    renderFeed();

    await waitFor(() => {
      expect(screen.getByTestId("action-items-feed")).toBeInTheDocument();
    });
    expect(screen.getByTestId("action-item-count")).toHaveTextContent("3");
    expect(screen.getByRole("link")).toHaveAttribute("href", "/approvals");
  });

  /**
   * The subtitle and the row badges describe the same thing — how much work
   * waits. Counting rows in the subtitle made the card say "1 pending" beside
   * a badge reading "2".
   */
  it("sums things to do in the subtitle, not rows", async () => {
    const approvalsItems: ActionItem[] = [
      {
        id: "approve-1",
        labelKey: "approvals:launcher.actionItems.pendingLabel",
        icon: Bell,
        severity: "warning",
        linkTo: "/approvals",
        count: 2,
      },
    ];
    const stockTakeItems: ActionItem[] = [
      {
        id: "count-1",
        labelKey: "inventory:actions.stockTakesInProgress",
        icon: Bell,
        severity: "warning",
        linkTo: "/inventory/stock-takes",
        count: 3,
      },
    ];
    moduleRegistry.getActionItemProviders = vi.fn(() => [
      { moduleName: "approvals", hook: () => approvalsItems },
      { moduleName: "stock_takes", hook: () => stockTakeItems },
    ]);

    renderFeed();

    await waitFor(() => {
      expect(
        screen.getByText("5 pending across enabled modules"),
      ).toBeInTheDocument();
    });
  });

  /**
   * The caption under a row is a module's user-visible name, resolved like
   * everywhere else — the registry identifier ("APPROVALS") is not a name
   *.
   */
  it("names the row by the module catalogue label, not the registry key", async () => {
    const sampleItems: ActionItem[] = [
      {
        id: "approve-1",
        labelKey: "approvals:launcher.actionItems.pendingLabel",
        icon: Bell,
        severity: "warning",
        linkTo: "/approvals",
        count: 1,
      },
    ];
    moduleRegistry.getActionItemProviders = vi.fn(() => [
      { moduleName: "approvals", hook: () => sampleItems },
    ]);

    renderFeed();

    await waitFor(() => {
      expect(screen.getByText("Approvals")).toBeInTheDocument();
    });
  });

  /**
   * Nothing to do is not news. The card used to hold its place with a heading
   * and "All done" inside it — and on first paint that was a claim made before
   * a single provider had answered, since an empty result and an unanswered
   * one look the same from here.
   */
  it("does not render the card while every provider returns nothing", async () => {
    moduleRegistry.register(makeModule("quiet", () => []));
    moduleRegistry.getActionItemProviders = vi.fn(() => [
      { moduleName: "quiet", hook: () => [] },
    ]);

    const { container } = renderFeed();

    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  /**
   * The collectors are the only thing that knows whether there is anything to
   * show. Hiding the card must not unmount them, or the card can never come
   * back.
   */
  it("follows a count that changes on a row it already shows", async () => {
    const row = (count: number): ActionItem[] => [
      {
        id: "same-row",
        labelKey: "approvals:action.reviewPending",
        icon: Bell,
        severity: "warning",
        linkTo: "/approvals",
        count,
      },
    ];
    let items = row(2);
    moduleRegistry.getActionItemProviders = vi.fn(() => [
      { moduleName: "counting", hook: () => items },
    ]);
    const tree = () => (
      <QueryClientProvider client={new QueryClient()}>
        <ModulesProvider>
          <MemoryRouter>
            <ActionItemsFeed />
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>
    );
    const { rerender } = render(tree());
    await waitFor(() =>
      expect(screen.getByTestId("action-item-count")).toHaveTextContent("2"),
    );

    items = row(1);
    rerender(tree());

    await waitFor(() =>
      expect(screen.getByTestId("action-item-count")).toHaveTextContent("1"),
    );
  });

  it("keeps collecting while the card is hidden, and shows it when work arrives", async () => {
    let items: ActionItem[] = [];
    moduleRegistry.getActionItemProviders = vi.fn(() => [
      { moduleName: "later", hook: () => items },
    ]);

    const { rerender, container } = renderFeed();
    await waitFor(() => expect(container).toBeEmptyDOMElement());

    items = [
      {
        id: "arrived-1",
        labelKey: "approvals:action.reviewPending",
        icon: Bell,
        severity: "info",
        linkTo: "/approvals",
      },
    ];
    rerender(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <ModulesProvider>
          <MemoryRouter>
            <ActionItemsFeed />
          </MemoryRouter>
        </ModulesProvider>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("action-items-feed")).toBeInTheDocument();
    });
  });
});
