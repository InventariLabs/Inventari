import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/utils";
import { useAuthStore } from "@/store/authStore";
import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { useArchivedItems } from "@/modules/inventory/hooks/useItems";
import {
  CONSUMPTION_REASONS,
  DELETION_REASONS,
  reasonLabelKey,
} from "@/modules/inventory/constants/stockReasons";
import en from "@/i18n/locales/en/items.json";
import pl from "@/i18n/locales/pl/items.json";
import de from "@/i18n/locales/de/items.json";
import es from "@/i18n/locales/es/items.json";
import fr from "@/i18n/locales/fr/items.json";
import { archivedReasonBadgeKey } from "@/modules/shared/lib/archiveReasons";
import ArchivedItemsPage from "./ArchivedItemsPage";

// jsdom's window.location is a static mock here, so navigation is asserted
// through the navigate spy instead of the address bar.
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock("@/modules/inventory/hooks/useItems", () => {
  return {
    useArchivedItems: vi.fn(),
  };
});

const mockUseArchivedItems = vi.mocked(useArchivedItems);

const archivedRows = [
  {
    id: "1",
    name: "Old Bread",
    deletion_reason: "other", // backend stores lowercase
    deletion_notes: "wrong product, entered by mistake",
    deleted_at: "2026-07-01T00:00:00Z",
    category: { name: "Bakery" },
  },
  {
    id: "2",
    name: "Milk",
    deletion_reason: "EXPIRED", // some paths store UPPERCASE
    deleted_at: "2026-07-02T00:00:00Z",
    category: { name: "Dairy" },
  },
  {
    id: "3",
    name: "Desk Lamp",
    deletion_reason: "ARCHIVED", // written by module flows (equipment register)
    deleted_at: "2026-07-03T00:00:00Z",
    category: { name: "Office equipment" },
  },
];

/** Stands in for the server: the rows come back filtered by the phrase the
 *  hook was handed, or unfiltered when no phrase reached it. If the page ever
 *  stops passing the phrase up, this stub answers with the full archive —
 *  and the render assertions below fail on the extra rows. */
function stubServerSearch(params?: {
  search?: string;
  offset?: number;
  limit?: number;
}): ReturnType<typeof useArchivedItems> {
  const needle = params?.search?.trim().toLowerCase();
  const rows = needle
    ? archivedRows.filter((row) => row.name.toLowerCase().includes(needle))
    : archivedRows;
  return {
    data: {
      items: rows,
      total: rows.length,
      limit: params?.limit ?? 50,
      offset: params?.offset ?? 0,
      has_more: false,
    },
    isLoading: false,
  } as unknown as ReturnType<typeof useArchivedItems>;
}

vi.mock("@/modules/inventory/hooks/useItemMutations", () => ({
  useRestoreItem: () => ({ mutate: vi.fn() }),
  usePurgeItem: () => ({ mutate: vi.fn() }),
}));

vi.mock("@/modules/settings/hooks/useOrganization", () => ({
  useOrganization: vi.fn(() => ({ data: null })),
  useShowModuleData: vi.fn(() => false),
}));

const purgeLabel = "Delete permanently";

/** The archive's two actions are permission-gated, so every test needs an
 *  account that holds them; the ones about denial narrow it themselves. */
function renderPage() {
  // The page names itself in the shell header now that no nav item lends it a
  // title, so the tests render the context it publishes to.
  return renderWithProviders(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: () => {} }}>
      <ArchivedItemsPage />
    </PageHeaderContext.Provider>,
  );
}

function signIn(permissions: string[]) {
  useAuthStore.setState({
    user: {
      is_blocked: false,
      is_superuser: false,
      is_active: true,
      id: "u-1",
      full_name: "Test User",
      email: "test@example.com",
      preferred_language: "en",
      role: "user",
      permissions,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    isAuthenticated: true,
  });
}

describe("ArchivedItemsPage", () => {
  beforeEach(() => {
    signIn(["items:write", "items:purge"]);
    mockUseArchivedItems.mockImplementation(stubServerSearch);
  });

  it("renders translated archive badges for lowercase DB reasons", () => {
    renderPage();

    // 'other' (lowercase) must resolve to the UPPERCASE key items:deletionReasons.OTHER
    expect(screen.getByText("Other")).toBeInTheDocument();
    // already-UPPERCASE reasons keep working
    expect(screen.getByText("Expired")).toBeInTheDocument();
    // no raw keys leak to the UI
    expect(screen.queryByText(/deletionReasons/i)).toBeNull();
  });

  it("shows the note given in the delete dialog next to the product, and none where there was none", () => {
    renderPage();

    expect(
      screen.getByText("wrong product, entered by mistake"),
    ).toBeInTheDocument();
    // Only the one row that carries a note gets the label.
    expect(screen.getAllByText("Note:")).toHaveLength(1);
  });

  it("translates the ARCHIVED reason the module flows write", () => {
    renderPage();

    // equipment's register and the storage archive soft-delete with
    // reason=ARCHIVED, which had no key — the badge read the composed key
    // out loud, in caps. Asserted inside the row: the tab trigger above the
    // table is called "Archived" too.
    const row = screen.getByText("Desk Lamp").closest("tr");
    expect(row).not.toBeNull();
    expect(row).toHaveTextContent("Archived");
    expect(screen.queryByText("ARCHIVED")).not.toBeInTheDocument();
  });

  it("names a reason with the word the delete dialog chose it by", () => {
    // Two dictionaries for the same codes had the archive say "Test data"
    // for what the dialog offered as "Test / erroneous data".
    for (const reason of DELETION_REASONS) {
      expect(archivedReasonBadgeKey(reason.toLowerCase())).toBe(
        reasonLabelKey(reason),
      );
    }
  });

  it("has a badge word for every reason the backend writes, in every language", () => {
    // The badge key is composed at render time, so the i18n key check cannot
    // see it — a reason missing from a locale surfaces as a raw key on the
    // screen. This is the guard that check cannot provide: the full set of
    // values `items.deletion_reason` can carry (the delete and consumption
    // vocabularies and the module-written ARCHIVED) against every locale's
    // deletionReasons — the dictionary the delete dialog chooses from.
    const reasons = [...DELETION_REASONS, ...CONSUMPTION_REASONS, "ARCHIVED"];
    const locales = { en, pl, de, es, fr } as const;

    for (const [name, catalogue] of Object.entries(locales)) {
      const badges = catalogue.deletionReasons as Record<string, string>;
      for (const reason of reasons) {
        expect(badges[reason], `${name} is missing ${reason}`).toBeTruthy();
      }
    }
  });

  it("hides the purge action when the org disabled permanent deletion", async () => {
    const { useOrganization } =
      await import("@/modules/settings/hooks/useOrganization");
    vi.mocked(useOrganization).mockReturnValue({
      data: {
        settings: { allow_permanent_delete: false },
        active_profile_id: "food_home",
      },
    } as unknown as ReturnType<typeof useOrganization>);

    renderPage();

    expect(screen.queryByText(purgeLabel)).toBeNull();
  });

  it("sends the phrase to the server and renders its answer", async () => {
    // Sixty rows of repeating names, no search and no filter, while the active
    // list has both: getting the right thing back was scrolling and guessing.
    // The page filtered the loaded page locally — a match on page 2 answered
    // "no matches" — so the phrase must reach the server and the server's
    // answer is what renders.
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByPlaceholderText(/search archived/i), "Milk");

    await waitFor(() => {
      expect(mockUseArchivedItems).toHaveBeenLastCalledWith(
        expect.objectContaining({ search: "Milk" }),
      );
    });
    expect(screen.getByText("Milk")).toBeInTheDocument();
    expect(screen.queryByText("Old Bread")).toBeNull();
  });

  it("says no matches only after the server answered empty", async () => {
    // While the phrase is still being typed (or is waiting out the debounce)
    // the archive cannot yet know it is empty — the old rows stay on screen
    // and the empty state keeps quiet until the server answers zero.
    const user = userEvent.setup();
    renderPage();

    await user.type(
      screen.getByPlaceholderText(/search archived/i),
      "Vanished",
    );

    expect(screen.queryByText(/no archived product matches/i)).toBeNull();
    expect(screen.getByText("Milk")).toBeInTheDocument();

    await screen.findByText(/no archived product matches/i);
    expect(screen.queryByText("Milk")).toBeNull();
    expect(
      screen.getByText(
        "Check the spelling or clear the search to see the whole archive.",
      ),
    ).toBeInTheDocument();
  });

  it("labels the deletion date, which stood there as a bare number", () => {
    renderPage();

    // The label moved from each row into the column header, where a table
    // keeps it: the value is still named, and it is named once.
    expect(
      screen.getByRole("columnheader", { name: /deleted/i }),
    ).toBeInTheDocument();
  });

  it("keeps the way back to the active list on the archive itself", async () => {
    // The archive lost its entry in the module navigation, so the pair of tabs
    // is now the only thing tying the two halves of one list together.
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByRole("tab", { name: "Archived" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await user.click(screen.getByRole("tab", { name: "Active" }));

    expect(mockNavigate).toHaveBeenCalledWith("/inventory/items");
  });

  it("an empty archive speaks about the archive, never about hidden module data", async () => {
    // Pin: the "Some products are hidden" state belongs to the active list,
    // where the module filter applies. This tab shows records that left every
    // list, so its empty state answers "where did the products I removed go".
    mockUseArchivedItems.mockReturnValue({
      data: { items: [], total: 0, limit: 50, offset: 0, has_more: false },
      isLoading: false,
    } as unknown as ReturnType<typeof useArchivedItems>);

    renderPage();

    expect(await screen.findByText("No archived products")).toBeInTheDocument();
    expect(screen.queryByText(/Some products are hidden/i)).toBeNull();
    expect(screen.queryByText(/switched-off module/i)).toBeNull();
  });

  it("asks the archive for the same module scope the active list uses", async () => {
    // The two tabs describe one population: with module data kept out of the
    // general lists, the archive must not list rows the active tab hides — a
    // restore would be confirmed where the row can never reappear.
    renderPage();

    await waitFor(() =>
      expect(mockUseArchivedItems).toHaveBeenLastCalledWith(
        expect.objectContaining({ exclude_module_contexts: true }),
      ),
    );
  });

  it("drops the scope when the organization shows module data", async () => {
    const { useShowModuleData } =
      await import("@/modules/settings/hooks/useOrganization");
    vi.mocked(useShowModuleData).mockReturnValue(true);

    try {
      renderPage();

      await waitFor(() =>
        expect(mockUseArchivedItems).toHaveBeenLastCalledWith(
          expect.objectContaining({ exclude_module_contexts: false }),
        ),
      );
    } finally {
      vi.mocked(useShowModuleData).mockReturnValue(false);
    }
  });

  it("offers neither action to an account that may not change products", async () => {
    // The API refuses restore without `items:write` and purge without
    // `items:purge`; the screen used to ask neither question and let the
    // refusal arrive after the click.
    signIn([]);
    const { useOrganization } =
      await import("@/modules/settings/hooks/useOrganization");
    vi.mocked(useOrganization).mockReturnValue({
      data: {
        settings: { allow_permanent_delete: true },
        active_profile_id: "food_home",
      },
    } as unknown as ReturnType<typeof useOrganization>);

    renderPage();

    expect(screen.queryByRole("button", { name: purgeLabel })).toBeNull();
    expect(screen.queryByRole("button", { name: /restore/i })).toBeNull();
    // An empty column headed "Actions" is a promise the screen cannot keep.
    expect(screen.queryByRole("columnheader", { name: /actions/i })).toBeNull();
  });

  it("restores when the account may write products", () => {
    signIn(["items:write"]);
    renderPage();

    expect(screen.getAllByRole("button", { name: /restore/i })).toHaveLength(3);
  });

  it("shows the purge action when the org allows permanent deletion", async () => {
    const { useOrganization } =
      await import("@/modules/settings/hooks/useOrganization");
    vi.mocked(useOrganization).mockReturnValue({
      data: {
        settings: { allow_permanent_delete: true },
        active_profile_id: "equipment_wms",
      },
    } as unknown as ReturnType<typeof useOrganization>);

    renderPage();

    // one archived item per row → one purge button each. Icon-only now, like
    // every other list, so the name is on the control rather than beside it.
    expect(screen.getAllByRole("button", { name: purgeLabel })).toHaveLength(3);
  });
});
