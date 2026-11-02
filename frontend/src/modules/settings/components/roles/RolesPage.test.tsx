import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import RolesPage from "./RolesPage";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const setHeader = vi.fn();
vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader }),
}));

const perm = (key: string) => ({
  key,
  label_key: `permissions:${key}`,
  description_key: null,
  default_roles: [],
});

const CATALOG = {
  system: [perm("items:read"), perm("items:write")],
  modules: [
    { module: "warehouse", permissions: [perm("warehouse:read")] },
    { module: "stock_takes", permissions: [perm("stock_takes:read")] },
    { module: "maker", permissions: [perm("maker:read")] },
    { module: "equipment", permissions: [perm("equipment:read")] },
  ],
};

const ROLE = {
  id: "role-1",
  organization_id: "org-1",
  name: "Warehouse operator",
  permissions: [
    "items:read",
    "warehouse:read",
    "stock_takes:read",
    "maker:read",
  ],
  is_system: false,
  created_at: null,
};

const SYSTEM_ROLE = { ...ROLE, id: "role-2", name: "Manager", is_system: true };

/** A built-in level as the backend sends it: the slug `User.role` stores. */
const BUILTIN_VIEWER = {
  id: "builtin-viewer",
  organization_id: null,
  name: "viewer",
  permissions: ["items:read"],
  is_system: true,
  created_at: null,
  member_count: 3,
};

function withRoles(roles: unknown[]) {
  server.use(
    http.get("*/roles/permission-catalog", () => HttpResponse.json(CATALOG)),
    http.get("*/roles", () => HttpResponse.json(onePage(roles))),
  );
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RolesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RolesPage", () => {
  it("says what each role can work with, without opening anything", async () => {
    // The screen this replaced needed thirty-three columns and sideways
    // scrolling to answer the same question.
    withRoles([ROLE]);
    renderPage();

    const table = await screen.findByTestId("roles-table");
    const row = within(table).getByText("Warehouse operator").closest("tr")!;
    expect(within(row).getByText(/General, Warehouse/)).toBeInTheDocument();
    // Four areas, three named and the rest counted.
    expect(within(row).getByText(/\+1$/)).toBeInTheDocument();
    expect(within(row).getByText("4")).toBeInTheDocument();
  });

  it("renders the same records as cards for a phone", async () => {
    withRoles([ROLE]);
    renderPage();

    const cards = await screen.findByTestId("roles-cards");
    expect(within(cards).getByText("Warehouse operator")).toBeInTheDocument();
  });

  it("marks a built-in role read-only and offers to view it", async () => {
    withRoles([SYSTEM_ROLE]);
    renderPage();

    const table = await screen.findByTestId("roles-table");
    expect(
      within(table).getByRole("button", { name: /view/i }),
    ).toBeInTheDocument();
    expect(within(table).queryByRole("button", { name: /^edit$/i })).toBeNull();
  });

  it("opens the editor for the role that was clicked", async () => {
    const user = userEvent.setup();
    withRoles([ROLE]);
    renderPage();

    const table = await screen.findByTestId("roles-table");
    await user.click(within(table).getByRole("button", { name: /^edit$/i }));

    expect(
      await screen.findByRole("dialog", { name: /Warehouse operator/i }),
    ).toBeInTheDocument();
  });

  it("explains itself when the organisation has no custom role", async () => {
    withRoles([]);
    renderPage();

    await waitFor(() =>
      expect(screen.getByText(/no custom roles yet/i)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("roles-table")).toBeNull();
  });

  it("names a built-in level the way the members list names it", async () => {
    // The backend sends the slug `User.role` holds. Showing "viewer" here
    // while the members screen shows "Viewer" is how a reader concludes the
    // two screens are talking about two different things.
    withRoles([BUILTIN_VIEWER]);
    renderPage();

    const table = await screen.findByTestId("roles-table");
    expect(within(table).getByText("Viewer")).toBeInTheDocument();
    expect(within(table).queryByText("viewer")).toBeNull();
  });

  it("answers what a built-in level may do, read-only", async () => {
    // The question the subtitle promises to answer — "what each role in this
    // organisation may do" — and the one it could not, because the four
    // levels every account holds are not rows in `roles`.
    const user = userEvent.setup();
    withRoles([BUILTIN_VIEWER]);
    renderPage();

    const table = await screen.findByTestId("roles-table");
    await user.click(within(table).getByRole("button", { name: /view/i }));

    const sheet = await screen.findByRole("dialog", { name: /Viewer/i });
    expect(within(sheet).getByText(/read-only/i)).toBeInTheDocument();
    expect(within(sheet).queryByRole("button", { name: /^save$/i })).toBeNull();
  });

  it("keeps the advice about custom roles once the table is never empty", async () => {
    // The empty state used to carry it. Built-in levels are always listed,
    // so the list has no empty state left to put it in.
    withRoles([BUILTIN_VIEWER]);
    renderPage();

    await screen.findByTestId("roles-table");
    expect(
      screen.getByText(/Built-in levels cover most cases/i),
    ).toBeInTheDocument();
  });

  it("drops that advice once a custom role exists", async () => {
    withRoles([BUILTIN_VIEWER, ROLE]);
    renderPage();

    await screen.findByTestId("roles-table");
    expect(screen.queryByText(/Built-in levels cover most cases/i)).toBeNull();
  });

  it("says on the row itself why a built-in role cannot be changed", async () => {
    // A padlock and a button reading "View" are what an administrator who may
    // change permissions read as "you may not".
    withRoles([BUILTIN_VIEWER, ROLE]);
    renderPage();

    const table = await screen.findByTestId("roles-table");
    const builtIn = within(table).getByText("Viewer").closest("tr")!;
    const custom = within(table).getByText("Warehouse operator").closest("tr")!;

    expect(within(builtIn).getByText(/built-in/i)).toBeInTheDocument();
    expect(within(custom).queryByText(/built-in/i)).toBeNull();
  });

  it("marks the phone card the same way", async () => {
    withRoles([BUILTIN_VIEWER]);
    renderPage();

    const cards = await screen.findByTestId("roles-cards");
    expect(within(cards).getByText(/built-in/i)).toBeInTheDocument();
  });

  it("keeps explaining the padlocks after a custom role exists", async () => {
    // The one sentence that said any of this appeared only while the
    // organisation had no role of its own — so it was gone by the second
    // visit, and the padlocks were not.
    withRoles([BUILTIN_VIEWER, ROLE]);
    renderPage();

    await screen.findByTestId("roles-table");
    expect(screen.getByText(/permissions are read-only/i)).toBeInTheDocument();
  });

  it("offers the way to a set of one's own from the same place", async () => {
    const user = userEvent.setup();
    withRoles([BUILTIN_VIEWER, ROLE]);
    renderPage();

    await screen.findByTestId("roles-table");
    const note = screen.getByText(/permissions are read-only/i);
    await user.click(
      within(note).getByRole("button", { name: /create role/i }),
    );

    expect(
      await screen.findByRole("dialog", { name: /create role/i }),
    ).toBeInTheDocument();
  });
});
