import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAuthStore } from "@/store/authStore";
import { QueryWrapper } from "@/test/queryWrapper";
import ItemHistoryTimeline, { ACTION_CONFIG } from "./ItemHistoryTimeline";
import { parseChanges } from "@/modules/inventory/utils/historyChanges";
import i18n, { withLanguage } from "@/test/mocks/i18n";
import type { ItemHistory } from "@/types";

// The hook the timeline reads its rows from — replaced wholesale so the
// test is about the reading, not the fetch.
vi.mock("@/modules/inventory/hooks/useItems", () => ({
  useItemDetailHistory: () => ({
    data: {
      pages: [
        {
          items: [
            {
              id: "h-1",
              action: "USED",
              changes: { qty: 1, old: 1, reason: "EXPIRED" },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-2",
              action: "USED",
              changes: { qty: 1, old: 2 },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-3",
              action: "DISPOSED",
              changes: { qty: 2, old: 5, reason: "DAMAGED" },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-4",
              action: "MOVED",
              changes: {
                from: "4c3d90a5-0000-0000-0000-000000000000",
                to: "717442c4-0000-0000-0000-000000000000",
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-6",
              action: "QUANTITY_CHANGED",
              changes: {
                old: 0,
                new: 1,
                document_type: "IN",
                document_number: "IN/2026/024",
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
              source_document_id: "ac5c24cb-0000-0000-0000-000000000000",
            },
            {
              id: "h-7",
              action: "QUANTITY_CHANGED",
              changes: {
                old: 1,
                new: 3,
                document_type: "CORRECTION",
                document_number: "CORRECTION/2026/001",
                corrects_document_number: "IN/2026/024",
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
              source_document_id: "bd6d35dc-0000-0000-0000-000000000000",
            },
            {
              id: "h-9",
              action: "DELETED",
              changes: {
                reason: "TEST_DATA",
                notes: "wrong product",
                old_quantity: 1,
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-10",
              action: "RESTORED",
              changes: {
                restored: true,
                previous_deletion_reason: "TEST_DATA",
                deleted_at: "2026-08-28T10:26:17.671992+00:00",
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-5",
              action: "UPDATED",
              changes: {
                old: { name: "Old name", expiry_date: "2026-01-01" },
                new: { name: "Butter", expiry_date: null },
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-8",
              action: "UPDATED",
              // The shape the edit sheet actually sends: the whole record on
              // both sides of the arrow, one field different.
              changes: {
                old: {
                  name: "Flour",
                  brand: "Mill",
                  quantity: 2,
                  uom_id: null,
                  storage_location_id: "4c3d90a5-0000-0000-0000-000000000000",
                },
                new: {
                  name: "Flour",
                  brand: "Mill",
                  quantity: 2,
                  uom_id: "g",
                  storage_location_id: "4c3d90a5-0000-0000-0000-000000000000",
                },
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-11",
              action: "STATUS_CHANGED",
              changes: { old_status: "AVAILABLE", new_status: "RETIRED" },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-12",
              action: "UPDATED",
              // The shape the backend writes since the names travel beside
              // the ids: one event, the words the journal already spells.
              changes: {
                old: {
                  category_id: "67d57628-1111-2222-3333-444455556666",
                  category_name: "Dairy",
                },
                new: {
                  category_id: "84f70f85-1111-2222-3333-444455556666",
                  category_name: "Drinks",
                },
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-13",
              action: "UPDATED",
              // The write hangs the shelf's name beside its id the way it
              // hangs the category's, so the row reads as a place without
              // asking the storages list behind this timeline anything.
              changes: {
                old: {
                  storage_location_id: "4c3d90a5-0000-0000-0000-000000000000",
                  storage_location_name: "Cold Storage",
                },
                new: {
                  storage_location_id: "717442c4-0000-0000-0000-000000000000",
                  storage_location_name: "Home",
                },
              },
              created_at: new Date().toISOString(),
              user_name: "Reader",
            },
            {
              id: "h-old",
              action: "USED",
              // Past a week the row stops counting backwards and names the
              // day — the label the old row printed in the browser's
              // language (see the test at the end of this file).
              changes: { qty: 42, old: 42 },
              created_at: "2026-01-15T10:00:00Z",
              user_name: "Reader",
            },
          ] as unknown as ItemHistory[],
        },
      ],
    },
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
    isLoading: false,
  }),
}));

// Which modules the organization runs. A link to a document is worth
// offering only where the module answering it is switched on.
const enabledModules = { value: ["warehouse"] };
vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => enabledModules.value,
}));

// The names a MOVED row resolves its ids against, read by id. Held outside the
// factory so a test can take them away: that is the state the read leaves
// behind when the request fails — nothing named.
const storagesRead = vi.hoisted(() => ({
  data: undefined as Array<{ id: string; name: string }> | undefined,
}));

const STORAGES = [
  { id: "4c3d90a5-0000-0000-0000-000000000000", name: "Cold Storage" },
  { id: "717442c4-0000-0000-0000-000000000000", name: "Home" },
];

vi.mock("@/hooks/queries/useLocations", () => ({
  useLocationsById: (ids: string[]) => ({
    byId: new Map(
      (storagesRead.data ?? [])
        .filter((place) => ids.includes(place.id))
        .map((place) => [place.id, place]),
    ),
  }),
}));

// The one question "where did it go" answers is why — the reason the dialog
// made the reader pick has to come back on the row, or the record of a
// thrown-out yoghurt reads the same as an eaten one.
function renderTimeline() {
  return render(
    <MemoryRouter>
      <QueryWrapper>
        <ItemHistoryTimeline itemId="item-1" />
      </QueryWrapper>
    </MemoryRouter>,
  );
}

function signIn(permissions: string[]) {
  useAuthStore.setState({
    user: {
      is_blocked: false,
      is_superuser: false,
      is_active: true,
      id: "u-1",
      full_name: "Reader",
      email: "reader@example.com",
      preferred_language: "en",
      role: "user",
      permissions,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    },
    isAuthenticated: true,
  });
}

beforeEach(() => {
  enabledModules.value = ["warehouse"];
  storagesRead.data = STORAGES;
  signIn(["warehouse:read"]);
});

describe("ItemHistoryTimeline — the reason has a reader", () => {
  it("shows the reason beside the quantity on a USED row", () => {
    renderTimeline();
    expect(screen.getByText(/1 · Expired/)).toBeInTheDocument();
  });

  it("keeps rows written without a reason readable", () => {
    renderTimeline();
    expect(screen.getByText(/^1$/)).toBeInTheDocument();
  });

  it("reads a DISPOSED row as disposal, not as eating", () => {
    renderTimeline();
    expect(screen.getByText(/2 · Damaged/)).toBeInTheDocument();
  });

  it("names the places a MOVED row names only by id", () => {
    // from/to arrive as location UUIDs — the only trace of a transfer the
    // app keeps, and it used to print "4c3d… → 7174…".
    renderTimeline();
    expect(screen.getByText("Cold Storage → Home")).toBeInTheDocument();
  });

  it("lists the fields an UPDATED row touched instead of both records", () => {
    // One row used to print half a screen of JSON.stringify for both
    // snapshots; the reader needs the field names.
    renderTimeline();
    expect(
      screen.getByText(
        "Product name: Old name → Butter · Expiry date: Jan 1, 2026 → —",
      ),
    ).toBeInTheDocument();
  });

  it("names one field when the edit sheet sent sixteen and changed one", () => {
    // The sheet PUTs the whole record, so the union of the two snapshots is
    // the size of the form, not the size of the edit.
    renderTimeline();
    expect(screen.getByText("Unit: — → g")).toBeInTheDocument();
    expect(screen.queryByText(/Storage location/)).not.toBeInTheDocument();
  });

  it("names a category the way the journal names the same event", () => {
    // The write records the name beside the id, and the card reads it —
    // the row used to say "Category: 67d57628 → 84f70f85" while the
    // organization journal spelled "Dairy → Drinks".
    renderTimeline();
    expect(screen.getByText("Category: Dairy → Drinks")).toBeInTheDocument();
  });

  it("names a lifecycle transition the way the asset timeline names it", () => {
    // STATUS_CHANGED fell through to the raw token in capitals; the asset
    // timeline has called the same event "Status changed" all along.
    renderTimeline();
    expect(screen.getByText("Status changed")).toBeInTheDocument();
    expect(screen.queryByText("STATUS_CHANGED")).not.toBeInTheDocument();
    expect(screen.getByText("Available → Retired")).toBeInTheDocument();
  });
});

/**
 * The storages read behind the names, failing.
 *
 * The timeline resolves the ids a MOVED row carries against the storages
 * list; the read may fail, and it then leaves no list behind. What this pins
 * is what a reader still gets: every row reads, a MOVED row takes the
 * shortened id the fallback gives a place nothing can name, and the row that
 * brought its own place name keeps it — the name travels in the row, the
 * list is only a second opinion about it.
 *
 * It documents that behaviour rather than guarding the read: drop the lookup
 * and the same words are on the screen, which is why this site was listed as
 * passing both ways. What it does refuse is the timeline going quiet or
 * throwing where the list is missing.
 */
describe("ItemHistoryTimeline — the places could not be named", () => {
  it("keeps the location name the row came with and reads the rows anyway", () => {
    storagesRead.data = undefined;
    renderTimeline();

    expect(
      screen.getByText("Location: Cold Storage → Home"),
    ).toBeInTheDocument();
    // This move knows the two shelves by id only, and nothing can name them.
    expect(screen.getByText("4c3d90a5 → 717442c4")).toBeInTheDocument();
    expect(screen.getByText("1 · Expired")).toBeInTheDocument();
  });
});

// The way back from a figure to the document that wrote it. The
// response has always carried the number; the row printed eight characters
// of the id instead, which the document search does not accept as input.
// Deleting and restoring are the two actions that describe undoing a
// mistake, and the two the timeline had no vocabulary for.
describe("ItemHistoryTimeline — undoing a mistake reads like the rest", () => {
  it("writes DELETED and RESTORED as words, not as raw action names", () => {
    renderTimeline();
    expect(screen.getByText("Deleted")).toBeInTheDocument();
    expect(screen.getByText("Restored")).toBeInTheDocument();
    expect(screen.queryByText(/^DELETED$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^RESTORED$/)).not.toBeInTheDocument();
  });

  it("keeps the reason and the note the deletion dialog collected", () => {
    renderTimeline();
    expect(
      screen.getByText(/Test \/ erroneous data · „wrong product"/),
    ).toBeInTheDocument();
  });

  it("does not print the deletion stamp as an ISO string", () => {
    renderTimeline();
    expect(screen.queryByText(/671992/)).not.toBeInTheDocument();
  });
});

describe("ItemHistoryTimeline — the road back to the document", () => {
  it("names the document instead of eight characters of its id", () => {
    renderTimeline();
    expect(screen.getByText("IN/2026/024")).toBeInTheDocument();
    expect(screen.queryByText(/ac5c24cb\.\.\./)).not.toBeInTheDocument();
  });

  it("makes the number lead to the document card", () => {
    renderTimeline();
    expect(screen.getByText("IN/2026/024").closest("a")).toHaveAttribute(
      "href",
      "/warehouse/documents/ac5c24cb-0000-0000-0000-000000000000",
    );
  });

  it("says which document a correction corrects", () => {
    renderTimeline();
    expect(screen.getByText("CORRECTION/2026/001")).toBeInTheDocument();
    expect(screen.getByText("corrects IN/2026/024")).toBeInTheDocument();
  });

  it("still names the document where the link would be refused", () => {
    // No right to read documents: the number is the useful half and stays;
    // the link would end in a denial after the click.
    signIn([]);
    renderTimeline();
    expect(screen.getByText("IN/2026/024")).toBeInTheDocument();
    expect(screen.getByText("IN/2026/024").closest("a")).toBeNull();
  });

  it("does not link into a module the organization does not run", () => {
    enabledModules.value = ["inventory"];
    renderTimeline();
    expect(screen.getByText("IN/2026/024").closest("a")).toBeNull();
  });
});

describe("ItemHistoryTimeline — an old row names its day", () => {
  /**
   * Past the "days ago" branch the row printed the day with
   * `toLocaleDateString(undefined, …)` — the language the browser is set up
   * in, not the one the interface is read in: a Polish screen said "Jan 15"
   * for anyone whose browser was English.
   */
  it("reads the day in the interface language", async () => {
    await withLanguage("pl", () => {
      renderTimeline();

      expect(screen.getByText("15 sty")).toBeInTheDocument();
      expect(screen.queryByText("Jan 15")).not.toBeInTheDocument();
    });
  });
});

/**
 * Every action the backend can write has a face on this timeline.
 *
 * STATUS_CHANGED was the one member of ItemAction with no entry, so it
 * printed as its raw token in capitals beside rows that read as words.
 * The contract test keeps the next member from doing the same:
 * the enum is the backend's, the config is this screen's.
 */
describe("ItemHistoryTimeline — every action has a face", () => {
  it("has a label and an icon for every ItemAction the backend declares", () => {
    const pySource = readFileSync(
      resolve(process.cwd(), "../backend/app/core/contracts/_system_dtos.py"),
      "utf-8",
    );
    const enumBlock = pySource.match(
      /class ItemAction\(StrEnum\):([\s\S]*?)(?=\nclass )/,
    );
    expect(enumBlock).not.toBeNull();
    const members = [
      ...enumBlock![1].matchAll(/^\s+(\w+)\s*=\s*'(\w+)'/gm),
    ].map((m) => m[2]);
    expect(members.length).toBeGreaterThan(0);

    for (const action of members) {
      expect(
        action in ACTION_CONFIG,
        `ItemAction.${action} prints as a raw token — add it to ACTION_CONFIG in ItemHistoryTimeline.tsx`,
      ).toBe(true);
    }
  });
});

// Direct units on the reader itself: the component tests
// above prove the screen; these prove the branches, including the fallback
// for a location that no longer exists.
describe("parseChanges (unit)", () => {
  const t = i18n.getFixedT(null, "items");
  const names = new Map([
    ["4c3d90a5-0000", "Cold Storage"],
    ["717442c4-0000", "Home"],
    ["4c3d90a5-0000-0000-0000-000000000000", "Cold Storage"],
    ["717442c4-0000-0000-0000-000000000000", "Home"],
  ]);
  const locationName = (id: string) => names.get(id);

  it("MOVED resolves both places to their names", () => {
    expect(
      parseChanges(
        "MOVED",
        { from: "4c3d90a5-0000", to: "717442c4-0000" },
        t,
        locationName,
      ),
    ).toBe("Cold Storage → Home");
  });

  it("MOVED falls back to a short id for a location that is gone", () => {
    expect(
      parseChanges(
        "MOVED",
        { from: "deadbeef-0000-0000-0000-000000000000" },
        t,
        locationName,
      ),
    ).toBe(`${t("history.from")}: deadbeef`);
  });

  it("UPDATED names the fields that moved, with both sides", () => {
    expect(
      parseChanges(
        "UPDATED",
        { old: { name: "a", expiry_date: "2026-01-01" }, new: { name: "b" } },
        t,
      ),
    ).toBe("Product name: a → b · Expiry date: Jan 1, 2026 → —");
  });

  it("UPDATED leaves out the fields the form resent unchanged", () => {
    expect(
      parseChanges(
        "UPDATED",
        { old: { name: "a", brand: "m" }, new: { name: "b", brand: "m" } },
        t,
      ),
    ).toBe("Product name: a → b");
  });

  it("UPDATED speaks of a place, not of the column that holds it", () => {
    // `storage_location_id` used to reach the screen as "storage location
    // id", and its value as eight characters of a UUID.
    expect(
      parseChanges(
        "UPDATED",
        {
          old: {
            storage_location_id: "4c3d90a5-0000-0000-0000-000000000000",
          },
          new: {
            storage_location_id: "717442c4-0000-0000-0000-000000000000",
          },
        },
        t,
        locationName,
      ),
    ).toBe("Location: Cold Storage → Home");
  });

  it("USED carries the reason the dialog collected", () => {
    expect(parseChanges("USED", { qty: 2, old: 5, reason: "EXPIRED" }, t)).toBe(
      "2 · Expired",
    );
  });

  it("QUANTITY_CHANGED tells the same story the journal tells", () => {
    // The journal showed this correction with its reason, the item's
    // own history kept only the numbers — one event, two stories. A stock
    // take correction names itself and carries the code the counter picked.
    expect(
      parseChanges(
        "QUANTITY_CHANGED",
        {
          old: 5,
          new: 4,
          reason: "stock_take_adjustment",
          discrepancy_reason_code: "LOSS",
        },
        t,
      ),
    ).toBe("5 → 4 · Stock take correction · Lost or taken");
  });

  it("QUANTITY_CHANGED stays a bare arrow when the write carried no reason", () => {
    expect(parseChanges("QUANTITY_CHANGED", { old: 2, new: 3 }, t)).toBe(
      "2 → 3",
    );
  });

  it("DELETED reads like the row about eating the same product", () => {
    expect(
      parseChanges(
        "DELETED",
        { reason: "TEST_DATA", notes: "wrong product", old_quantity: 1 },
        t,
      ),
    ).toBe('1 · Test / erroneous data · „wrong product"');
  });

  it("RESTORED says where the record came back from, without an ISO stamp", () => {
    const line = parseChanges(
      "RESTORED",
      {
        restored: true,
        previous_deletion_reason: "TEST_DATA",
        deleted_at: "2026-08-28T10:26:17.671992+00:00",
      },
      t,
    );
    expect(line).toBe("Restored from the archive · Test / erroneous data");
    expect(line).not.toContain("2026-08-28T");
  });
});
