import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import AssetListPage from "../pages/AssetListPage";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

const emptyPage = {
  items: [],
  total: 0,
  offset: 0,
  limit: 50,
  has_more: false,
};

function Address() {
  const { search } = useLocation();
  return <output data-testid="address">{search}</output>;
}

function renderList(entry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[entry]}>
          <AssetListPage />
          <Address />
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

const chip = (key: string) => screen.getByTestId(`filter-${key}`);
const isLit = (el: HTMLElement) => el.className.includes("ring-primary-500");

describe("AssetListPage — what the address says is what the controls show", () => {
  it("lights the Checked Out chip, not All, for ?checked_out=1", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () => HttpResponse.json(emptyPage)),
    );
    renderList("/equipment/assets?checked_out=1");

    await screen.findByText("No assets are checked out");
    expect(isLit(chip("DEPLOYED"))).toBe(true);
    expect(isLit(chip("all"))).toBe(false);
  });

  it("'All' drops the checked-out flag from the address", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/equipment/assets", () => HttpResponse.json(emptyPage)),
    );
    renderList("/equipment/assets?checked_out=1");

    await screen.findByText("No assets are checked out");
    await user.click(chip("all"));
    await waitFor(() =>
      expect(screen.getByTestId("address")).toHaveTextContent(/^$/),
    );
    expect(isLit(chip("all"))).toBe(true);
  });

  it("keeps the search phrase in the address and reads it back from there", async () => {
    let requested = "";
    server.use(
      http.get("/api/v1/equipment/assets", ({ request }) => {
        requested = new URL(request.url).search;
        return HttpResponse.json(emptyPage);
      }),
    );
    renderList("/equipment/assets?q=QA");

    expect(screen.getByTestId("list-search-input")).toHaveValue("QA");
    await waitFor(() => expect(requested).toContain("search=QA"));

    fireEvent.change(screen.getByTestId("list-search-input"), {
      target: { value: "Dell" },
    });
    await waitFor(() =>
      expect(screen.getByTestId("address")).toHaveTextContent("q=Dell"),
    );
  });
});

describe("AssetListPage — a search that matches nothing", () => {
  it("says nothing matches, not that the register is empty, and clears the phrase", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/v1/equipment/assets", () => HttpResponse.json(emptyPage)),
    );
    renderList("/equipment/assets?q=zzzzqq");

    expect(
      await screen.findByRole("heading", {
        name: "No assets match your search",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No assets yet. Add your first asset."),
    ).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() =>
      expect(screen.getByTestId("address")).toHaveTextContent(/^$/),
    );
    expect(screen.getByTestId("list-search-input")).toHaveValue("");
  });
});
