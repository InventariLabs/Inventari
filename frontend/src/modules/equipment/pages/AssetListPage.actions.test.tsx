import React from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

import AssetListPage from "./AssetListPage";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
  },
}));

vi.mock("@/contexts/ModulesContext", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/ModulesContext")>()),
  useModules: () => ({
    enabledModules: ["equipment"],
    isModuleEnabled: () => true,
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

function asset(n: number) {
  return {
    id: `asset-${n}`,
    name: `Laptop ${n}`,
    quantity: 1,
    metadata: { equipment: { equipment_status: "AVAILABLE" } },
  };
}

const ARCHIVED = {
  id: "asset-9",
  name: "Old Printer",
  quantity: 1,
  is_deleted: true,
  metadata: { equipment: { equipment_status: "RETIRED" } },
};

let listRequests: URLSearchParams[];

beforeEach(() => {
  listRequests = [];
  signInWith(["equipment:read", "equipment:write", "items:read"]);
  server.use(
    http.get("/api/v1/categories", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/locations", () =>
      HttpResponse.json(
        onePage([{ id: "loc-1", name: "Server Room", items_count: 0 }]),
      ),
    ),
    http.get("/api/v1/equipment/models", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/partners", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/equipment/assets", ({ request }) => {
      listRequests.push(new URL(request.url).searchParams);
      return HttpResponse.json({
        items: [asset(1), asset(2)],
        total: 2,
        offset: 0,
        limit: 50,
        has_more: false,
      });
    }),
    http.get("/api/v1/items/archived", () =>
      HttpResponse.json({ items: [ARCHIVED], total: 1, offset: 0, limit: 50 }),
    ),
  );
});

afterEach(() => {
  signOut();
});

function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {data.actions ? <div>{data.actions}</div> : null}
      {children}
    </PageHeaderContext.Provider>
  );
}

function renderList() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/equipment/assets"]}>
        <PageHeaderHost>
          <AssetListPage />
        </PageHeaderHost>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

const lastList = () => listRequests[listRequests.length - 1];

async function selectEverything(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /select all/i }));
}

/**
 * The bulk bar's buttons open a confirmation, and only the confirmation
 * sends. The failures caught: a bar button wired to the wrong dialog, a
 * confirmation that sends a different selection than the one on screen,
 * and a cancel that still sends.
 */
describe("AssetListPage — bulk actions over the selection", () => {
  it("retires the selection after the confirmation names how many", async () => {
    let sent: string[] = [];
    server.use(
      http.post("/api/v1/equipment/items/bulk-retire", async ({ request }) => {
        sent = (await request.json()) as string[];
        return HttpResponse.json({ retired: 2, errors: [] });
      }),
    );
    const user = renderList();
    await selectEverything(user);

    await user.click(screen.getByRole("button", { name: /Retire Selected/ }));
    const dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText("Retire 2 selected assets?"),
    ).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole("button", { name: "Retire Selected" }),
    );

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("2 assets retired"),
    );
    expect(sent).toEqual(["asset-1", "asset-2"]);
  });

  it("archives the selection, and a cancelled archive sends nothing", async () => {
    const archived = vi.fn();
    server.use(
      http.post("/api/v1/equipment/items/bulk-archive", async ({ request }) => {
        archived(await request.json());
        return HttpResponse.json({ archived: 2, errors: [] });
      }),
    );
    const user = renderList();
    await selectEverything(user);

    await user.click(screen.getByRole("button", { name: /Archive Selected/ }));
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(archived).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /Archive Selected/ }));
    dialog = await screen.findByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", { name: "Archive Selected" }),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("2 assets archived"),
    );
    expect(archived).toHaveBeenCalledWith(["asset-1", "asset-2"]);
  });

  it("opens the status, location and assignee editors from the bar", async () => {
    const user = renderList();
    await selectEverything(user);

    await user.click(screen.getByRole("button", { name: "Status" }));
    expect(
      await screen.findByText("Change status of 2 assets"),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(
        screen.queryByText("Change status of 2 assets"),
      ).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Location" }));
    expect(
      await screen.findByText("Move 2 assets to a location"),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Assign" }));
    expect(
      await screen.findByText("Assign 2 assets to a person"),
    ).toBeInTheDocument();
  });
});

describe("AssetListPage — the archive tab", () => {
  it("restores an archived asset after the confirmation", async () => {
    const restored = vi.fn();
    server.use(
      http.post("/api/v1/items/asset-9/restore", () => {
        restored();
        return HttpResponse.json(ARCHIVED);
      }),
    );
    const user = renderList();
    await screen.findAllByText("Laptop 1");

    await user.click(screen.getByRole("tab", { name: /Archived/ }));
    await screen.findByText("Old Printer");
    await user.click(screen.getByRole("button", { name: /Restore/ }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Restore" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Asset restored"),
    );
    expect(restored).toHaveBeenCalledTimes(1);
  });

  it("purges an archived asset, and cancelling the purge sends nothing", async () => {
    const purged = vi.fn();
    server.use(
      http.post("/api/v1/equipment/items/bulk-purge", async ({ request }) => {
        purged(await request.json());
        return HttpResponse.json({ purged: 1, errors: [] });
      }),
    );
    const user = renderList();
    await screen.findAllByText("Laptop 1");
    await user.click(screen.getByRole("tab", { name: /Archived/ }));
    await screen.findByText("Old Printer");

    await user.click(
      screen.getByRole("button", { name: /Delete Permanently/ }),
    );
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(purged).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: /Delete Permanently/ }),
    );
    dialog = await screen.findByRole("alertdialog");
    await user.click(
      within(dialog).getByRole("button", { name: "Delete Permanently" }),
    );
    await waitFor(() => expect(purged).toHaveBeenCalledWith(["asset-9"]));
  });
});

describe("AssetListPage — narrowing and ordering the list", () => {
  it("sends the chosen status chip and sort order with the list request", async () => {
    const user = renderList();
    await screen.findAllByText("Laptop 1");

    await user.click(screen.getByRole("button", { name: "Maintenance" }));
    await waitFor(() => expect(lastList().get("status")).toBe("MAINTENANCE"));

    await user.click(screen.getByRole("button", { name: "All" }));
    await waitFor(() => expect(lastList().get("status")).toBeNull());

    fireEvent.change(screen.getByRole("combobox", { name: "Sort assets" }), {
      target: { value: "name:asc" },
    });
    await waitFor(() => expect(lastList().get("sort")).toBe("name"));
    expect(lastList().get("sort_dir")).toBe("asc");
  });

  it("opens the import from the header and closes it again", async () => {
    const user = renderList();
    await screen.findAllByText("Laptop 1");

    await user.click(screen.getByRole("button", { name: "Import" }));
    expect(
      await screen.findByText("Import Equipment from CSV / XLSX"),
    ).toBeInTheDocument();
    await user.click(screen.getByText("Cancel", { selector: "button" }));
    await waitFor(() =>
      expect(
        screen.queryByText("Import Equipment from CSV / XLSX"),
      ).not.toBeInTheDocument(),
    );
  });
});
