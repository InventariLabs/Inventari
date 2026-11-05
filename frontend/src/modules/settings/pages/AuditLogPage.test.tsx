import { render, screen, fireEvent, waitFor, within } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import AuditLogPage from "./AuditLogPage";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";

/**
 * Two defects this page carried that a type-checker cannot see.
 *
 * The subtitle spelled the action enum out — `CREATE / UPDATE / SOFT_DELETE /
 * PURGE` — inside a sentence every language otherwise translated, so the one
 * part naming what the log records was the one part nobody could read, and it
 * matched none of the labels on the badges directly below it.
 *
 * The "Since" filter was a native `datetime-local`: it formatted itself from
 * the browser's locale (`dd.mm.rrrr, --:--`) beside a table formatted from the
 * app's, and carried the platform's calendar button rather than the app's.
 */

const EMPTY_PAGE = {
  items: [],
  total: 0,
  limit: 100,
  offset: 0,
  has_more: false,
};

/** Renders the page and hands back the header it gave the shell. */
function renderPage() {
  const header: { current: PageHeaderData } = { current: {} };
  const setHeader = vi.fn((data: PageHeaderData) => {
    header.current = data;
  });

  render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader }}>
      <AuditLogPage />
    </PageHeaderContext.Provider>,
  );

  return header;
}

/**
 * Runs `click` with the download plumbing stubbed, and hands back what the
 * page wrote into the CSV.
 *
 * jsdom implements neither a Blob a test can read nor navigation, so the
 * anchor's click would land on "Not implemented: navigation" after the test
 * ends.
 */
async function captureCsv(click: () => Promise<void>): Promise<string> {
  const written: string[] = [];
  const originalBlob = globalThis.Blob;
  class CapturingBlob extends originalBlob {
    constructor(parts: BlobPart[], options?: BlobPropertyBag) {
      written.push(parts.map(String).join(""));
      super(parts, options);
    }
  }
  globalThis.Blob = CapturingBlob as unknown as typeof Blob;
  globalThis.URL.createObjectURL = () => "blob:audit";
  globalThis.URL.revokeObjectURL = () => {};
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});

  try {
    await click();
  } finally {
    globalThis.Blob = originalBlob;
    clickSpy.mockRestore();
  }

  return written.join("");
}

async function exportCsv() {
  await userEvent.click(screen.getByRole("button", { name: /export|csv/i }));
}

/**
 * The maker journal's snapshot shape — flat context beside a before/after
 * pair — as the recipe journal writes it (recipe_service's
 * log_recipe_change). The writer × reader composition is pinned at the
 * parser level elsewhere; this page-level case renders it through the
 * component a person actually reads.
 */
const MAKER_RECIPE_ENTRY = {
  id: "e1",
  organization_id: "org-1",
  user_id: null,
  user_email: "baker@example.com",
  action: "UPDATE",
  target_type: "maker_recipe",
  target_id: "recipe-1",
  snapshot: {
    name: "Powidła śliwkowe",
    ingredient: "Cukier biały",
    // The writer keeps only the keys whose value changed, so a change of the
    // quantity alone carries no unit on either side.
    before: { qty_per_batch: 2 },
    after: { qty_per_batch: 5 },
  },
  reason: null,
  meta_data: null,
  created_at: "2026-09-13T10:00:00Z",
};

describe("AuditLogPage — the maker journal reads in the reader's words", () => {
  it("renders a recipe change as its two sides beside its context, in Polish", async () => {
    await withLanguage("pl", async () => {
      server.use(
        http.get("/api/v1/audit-log", () =>
          HttpResponse.json({
            items: [MAKER_RECIPE_ENTRY],
            total: 1,
            limit: 100,
            offset: 0,
            has_more: false,
          }),
        ),
      );

      renderPage();

      // Both responsive variants render in jsdom, so a line appears twice —
      // once in the table, once on the card.
      const qtyLines = await screen.findAllByText((_, element) => {
        return (
          element?.tagName === "DIV" &&
          (element as HTMLElement).textContent === "Ilość na partię: 2 → 5"
        );
      });
      expect(qtyLines.length).toBeGreaterThanOrEqual(1);
      const ingredientLines = await screen.findAllByText((_, element) => {
        return (
          element?.tagName === "DIV" &&
          (element as HTMLElement).textContent === "Składnik: Cukier biały"
        );
      });
      expect(ingredientLines.length).toBeGreaterThanOrEqual(1);
    });
  });
});

/**
 * An empty journal is two different states, and "no entries match the current
 * filters" was the answer to both: an organization that had not done anything
 * yet read its own emptiness as a filter problem it did not have.
 */
describe("AuditLogPage — the empty journal says which emptiness it is", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/audit-log", () => HttpResponse.json(EMPTY_PAGE)),
      http.get("/api/v1/audit-log/target-types", () => HttpResponse.json([])),
    );
  });

  it("says the filter lists could not be loaded instead of offering none", async () => {
    server.use(
      http.get(
        "/api/v1/audit-log/target-types",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    renderPage();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("says the server could not be reached when nothing answers", async () => {
    // An open session with the server down: the journal and both of its
    // filter lists fail without an answer. Each said "An error occurred",
    // while the full-page outage screen names the cause.
    server.use(
      http.get("/api/v1/audit-log", () => HttpResponse.error()),
      http.get("/api/v1/audit-log/target-types", () => HttpResponse.error()),
    );
    renderPage();

    const said = await screen.findAllByText("Cannot reach the server");
    expect(said.length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("An error occurred")).not.toBeInTheDocument();
  });

  it("says the server could not be reached when a proxy answers for it", async () => {
    // The dev server's proxy, or a reverse proxy in production, answers a
    // stopped backend with a 502 of its own — an answer, but not the server's.
    server.use(
      http.get(
        "/api/v1/audit-log",
        () => new HttpResponse("<html>Bad gateway</html>", { status: 502 }),
      ),
      http.get("/api/v1/audit-log/target-types", () => HttpResponse.json([])),
    );
    renderPage();

    expect(
      await screen.findByText("Cannot reach the server"),
    ).toBeInTheDocument();
    expect(screen.queryByText("An error occurred")).not.toBeInTheDocument();
  });

  it("says there are no entries yet when no filter is set", async () => {
    renderPage();

    expect(
      await screen.findByText("No audit entries yet."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No audit entries match the current filters."),
    ).not.toBeInTheDocument();
  });

  it("keeps the filter wording once a filter is set", async () => {
    server.use(
      http.get("/api/v1/audit-log/target-types", () =>
        HttpResponse.json(["module"]),
      ),
    );

    renderPage();

    await screen.findByRole("option", { name: "Module" });
    await userEvent.selectOptions(
      screen.getByLabelText("Target type"),
      "module",
    );

    expect(
      await screen.findByText("No audit entries match the current filters."),
    ).toBeInTheDocument();
    expect(screen.queryByText("No audit entries yet.")).not.toBeInTheDocument();
  });
});

describe("AuditLogPage", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/audit-log", () => HttpResponse.json(EMPTY_PAGE)),
      http.get("/api/v1/audit-log/target-types", () => HttpResponse.json([])),
      // Read only when a key's row is on the page; an empty catalogue leaves
      // the permissions to the key module's own wording.
      http.get("/api/v1/roles/permission-catalog", () =>
        HttpResponse.json({ system: [], modules: [] }),
      ),
    );
  });

  it("names the recorded actions with the labels the badges use", async () => {
    const header = renderPage();

    expect(header.current.subtitle).toContain(
      "Create · Update · Quantity change · Move · Use · Dispose · Restore · Soft delete · Purge",
    );
    expect(
      await screen.findByText("No audit entries yet."),
    ).toBeInTheDocument();
  });

  it("translates that sentence instead of leaving the enum in it", async () => {
    await withLanguage("pl", async () => {
      const header = renderPage();

      expect(header.current.subtitle).toContain("Archiwizacja");
      expect(header.current.subtitle).not.toMatch(/CREATE|SOFT_DELETE|PURGE/);
      expect(
        await screen.findByText("Brak wpisów audytu."),
      ).toBeInTheDocument();
    });
  });

  it("filters from the app's own date field, asking the API for a whole day", async () => {
    const since: string[] = [];
    server.use(
      http.get("/api/v1/audit-log", ({ request }) => {
        since.push(new URL(request.url).searchParams.get("since") ?? "");
        return HttpResponse.json(EMPTY_PAGE);
      }),
    );

    renderPage();
    expect(document.querySelector('input[type="datetime-local"]')).toBeNull();

    fireEvent.click(screen.getByRole("combobox", { name: /^since$/i }));
    fireEvent.click(screen.getByRole("button", { name: "A week ago" }));

    // A plain `yyyy-MM-dd`, which the backend widens to midnight — no clock
    // component to read one way here and another on the server.
    await waitFor(() =>
      expect(since[since.length - 1]).toMatch(/^\d{4}-\d{2}-\d{2}$/),
    );
    expect(
      await screen.findByText("No audit entries match the current filters."),
    ).toBeInTheDocument();
  });

  it("offers the target types the log holds, not a list written into the page", async () => {
    // Three values were typed here: `item`, `document`, `purchase_order`.
    // Two belong to modules a given profile does not install, so those
    // filters could only ever answer "no entries", while the things that
    // really changed — members, modules, settings — had no entry at all.
    server.use(
      http.get("/api/v1/audit-log/target-types", () =>
        HttpResponse.json(["api_key", "module", "organization"]),
      ),
    );

    renderPage();

    expect(
      await screen.findByRole("option", { name: "API key" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Module" })).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Purchase order" }),
    ).not.toBeInTheDocument();
  });

  it("asks the API for both ends of the range", async () => {
    const calls: URL[] = [];
    server.use(
      http.get("/api/v1/audit-log", ({ request }) => {
        calls.push(new URL(request.url));
        return HttpResponse.json(EMPTY_PAGE);
      }),
    );

    renderPage();

    fireEvent.click(screen.getByRole("combobox", { name: /^until$/i }));
    fireEvent.click(screen.getByRole("button", { name: "Today" }));

    await waitFor(() =>
      expect(calls[calls.length - 1].searchParams.get("until")).toMatch(
        /^\d{4}-\d{2}-\d{2}$/,
      ),
    );
  });

  it("turns the page by the cursor the page on screen carried, and back", async () => {
    // The journal pages by the last entry seen: page two is asked for with
    // the first page's cursor, never with a position that would make the
    // server count every entry above it.
    const calls: URL[] = [];
    server.use(
      http.get("/api/v1/audit-log", ({ request }) => {
        const url = new URL(request.url);
        calls.push(url);
        const second = url.searchParams.get("cursor") === "after-100";
        return HttpResponse.json({
          items: [MAKER_RECIPE_ENTRY],
          total: 250,
          limit: 100,
          offset: second ? 100 : 0,
          has_more: !second,
          next_cursor: second ? null : "after-100",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Next page" }));

    await waitFor(() =>
      expect(calls[calls.length - 1].searchParams.get("cursor")).toBe(
        "after-100",
      ),
    );
    expect(calls[calls.length - 1].searchParams.has("offset")).toBe(false);

    await user.click(
      await screen.findByRole("button", { name: "Previous page" }),
    );

    await waitFor(() =>
      expect(calls[calls.length - 1].searchParams.has("cursor")).toBe(false),
    );
  });

  it("starts again from the first page when a filter changes", async () => {
    const calls: URL[] = [];
    server.use(
      http.get("/api/v1/audit-log", ({ request }) => {
        calls.push(new URL(request.url));
        return HttpResponse.json({
          items: [MAKER_RECIPE_ENTRY],
          total: 250,
          limit: 100,
          offset: 0,
          has_more: true,
          next_cursor: "after-100",
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Next page" }));
    await waitFor(() =>
      expect(calls[calls.length - 1].searchParams.get("cursor")).toBe(
        "after-100",
      ),
    );

    fireEvent.click(screen.getByRole("combobox", { name: /^since$/i }));
    fireEvent.click(screen.getByRole("button", { name: "A week ago" }));

    await waitFor(() => {
      const last = calls[calls.length - 1].searchParams;
      expect(last.get("since")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(last.has("cursor")).toBe(false);
    });
  });

  it("says which setting moved instead of only that something did", async () => {
    // "Update · Organization settings" with an empty Detail column left the
    // reader to guess what an administrator had changed.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "organization",
              target_id: "o1",
              snapshot: {
                name: "Test Org",
                before: { allow_permanent_delete: false },
                after: { allow_permanent_delete: true },
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    // The field is named the way a person would say it, not the way the
    // column is spelled, and the values read in the same language: the
    // boolean is an answer, so it comes from the catalogue now.
    expect(
      await screen.findByText("Permanent delete allowed:"),
    ).toBeInTheDocument();
    expect(screen.getByText(/No → Yes/)).toBeInTheDocument();
  });

  it("reads the names of the screens, not the keys of the code", async () => {
    // A module switched on wrote `maker` as its target, the onboarding wrote
    // `equipment_wms` and a list of module keys, and an organization setting
    // read `show_module_data` — none of which a reader has met on a screen.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 3,
          items: [
            {
              id: "m1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "module",
              target_id: "o1",
              snapshot: {
                name: "maker",
                before: { enabled: false },
                after: { enabled: true },
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:03:00Z",
            },
            {
              id: "p1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "product_profile",
              target_id: "o1",
              snapshot: {
                name: "equipment_wms",
                before: { enabled_modules: ["core"] },
                after: {
                  profile_id: "equipment_wms",
                  enabled_modules: [
                    "announcements",
                    "categories",
                    "core",
                    "items",
                    "locations",
                  ],
                },
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:02:00Z",
            },
            {
              id: "s1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "organization",
              target_id: "o1",
              snapshot: {
                name: "Test Org",
                before: { show_module_data: true },
                after: { show_module_data: false },
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:01:00Z",
            },
          ],
        }),
      ),
    );

    // The module rows ask the module for its setting titles.
    server.use(
      http.get("/api/v1/modules/maker/settings", () =>
        HttpResponse.json({
          settings: {},
          settings_schema: { properties: {} },
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("Show module data in general lists:"),
    ).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    const text = rows.map((row) => row.textContent).join("\n");
    // The module and the mode by the names their own screens print.
    expect(text).not.toMatch(/\bmaker\b/);
    expect(text).not.toMatch(/equipment_wms/);
    expect(text).not.toMatch(/show_module_data/);
    // Every built-in key of an onboarding set reads as a name, not a key.
    expect(text).not.toMatch(
      /\b(announcements|categories|core|items|locations)\b/,
    );
    expect(text).toMatch(
      /Announcements, Categories, Basics, Inventory, Locations/,
    );
    expect(text).toMatch(/Workspace mode:\s*—\s*→\s*Equipment/);
  });

  it("names the invited address and role, and calls a revocation a revocation", async () => {
    // The entry sat under the organization's id and the address was one click
    // deep; taking an invitation back was filed under "Soft delete".
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 2,
          items: [
            {
              id: "i2",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "SOFT_DELETE",
              target_type: "invitation",
              target_id: "7d6f4bf7-1111-2222-3333-444455556666",
              snapshot: { invited_email: "anna@example.com", role: "user" },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:05:00Z",
            },
            {
              id: "i1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "CREATE",
              target_type: "invitation",
              target_id: "7d6f4bf7-1111-2222-3333-444455556666",
              snapshot: {
                expires_at: "2026-08-27T10:00:00+00:00",
                role: "viewer",
                invited_email: "ben@example.com",
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("anna@example.com · Member"),
    ).toBeInTheDocument();
    expect(screen.getByText("ben@example.com · Viewer")).toBeInTheDocument();
    expect(screen.getByText("Revoked")).toBeInTheDocument();
    expect(screen.queryByText("Soft delete")).not.toBeInTheDocument();
  });

  // The log files an access taken back as a soft delete and an access given as
  // a "use". Every kind of record whose act has a word of its own is listed
  // here, so a third record kind that borrows the stock vocabulary fails on
  // the one line that names it.
  it.each([
    ["invitation", "SOFT_DELETE", "Revoked"],
    ["invitation", "USE", "Accepted"],
    ["api_key", "SOFT_DELETE", "Revoked"],
  ])(
    "calls %s %s by its own verb: %s",
    async (target_type, action, expected) => {
      server.use(
        http.get("/api/v1/audit-log", () =>
          HttpResponse.json({
            ...EMPTY_PAGE,
            total: 1,
            items: [
              {
                id: "x1",
                organization_id: "o1",
                user_id: "u1",
                user_email: "admin@example.com",
                action,
                target_type,
                target_id: "7d6f4bf7-1111-2222-3333-444455556666",
                snapshot: { name: "CI", key_prefix: "inv_live_b3be" },
                reason: null,
                meta_data: null,
                created_at: "2026-08-20T10:05:00Z",
              },
            ],
          }),
        ),
      );

      renderPage();

      expect(await screen.findByText(expected)).toBeInTheDocument();
      expect(screen.queryByText("Soft delete")).not.toBeInTheDocument();
      expect(screen.queryByText("Use")).not.toBeInTheDocument();
    },
  );

  it("tells a profile's own settings from the person's edit of a setting", async () => {
    server.use(
      http.get("/api/v1/modules/equipment/settings", () =>
        HttpResponse.json({
          settings: {},
          settings_schema: { properties: {} },
        }),
      ),
    );
    // Choosing a workspace mode writes the profile's warning windows under
    // the person who chose it; the row used to read as their own "Update".
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 2,
          items: [
            {
              id: "m2",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "module",
              target_id: "7d6f4bf7-1111-2222-3333-444455556666",
              snapshot: { name: "equipment", subject: "profile:equipment_wms" },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:05:00Z",
            },
            {
              id: "m1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "module",
              target_id: "7d6f4bf7-1111-2222-3333-444455556666",
              snapshot: { name: "equipment" },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("Workspace mode default"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Update")).toHaveLength(1);
  });

  it("lists a key's permissions by the labels the key dialog shows", async () => {
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "k1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "CREATE",
              target_type: "api_key",
              target_id: "7d6f4bf7-1111-2222-3333-444455556666",
              snapshot: {
                name: "CI",
                key_prefix: "inv_live_b3be",
                permissions: ["items:read", "locations:read"],
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:05:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText(/Read products and stock levels, Read locations/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/items:read/)).not.toBeInTheDocument();
  });

  it("reads a module's permission by the catalogue label the dialog shows", async () => {
    // `printing:agent` has no sentence of the key module's own; the dialog
    // and the key list take its label from the permission catalogue, and the
    // journal showed the raw key.
    server.use(
      http.get("/api/v1/roles/permission-catalog", ({ request }) =>
        // The audit log asks for every module's permissions: a key issued
        // while API Keys or Printing was on is read the same when it is off.
        new URL(request.url).searchParams.get("all_modules") === "true"
          ? HttpResponse.json({
              system: [],
              modules: [
                {
                  module: "printing",
                  permissions: [
                    {
                      key: "printing:agent",
                      label_key: "printing:permissions.agent",
                      description_key: "printing:permissions.agent",
                      default_roles: [],
                    },
                  ],
                },
              ],
            })
          : HttpResponse.json({ system: [], modules: [] }),
      ),
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "k2",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "CREATE",
              target_type: "api_key",
              target_id: "7d6f4bf7-1111-2222-3333-444455556666",
              snapshot: {
                name: "Print agent",
                key_prefix: "inv_live_b3be",
                permissions: ["printing:agent"],
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:05:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText(/Act as a print agent/)).toBeInTheDocument();
    expect(screen.queryByText(/printing:agent/)).not.toBeInTheDocument();
  });

  it("names a module's setting the way the settings screen names it", async () => {
    // A settings change was journaled under the stored key, which the reader
    // then saw as "Allow admin self approve" — words that appear on no screen,
    // in a language the interface never shows. The module's own schema is what
    // the settings screen reads its field names from.
    await withLanguage("pl", async () => {
      server.use(
        http.get("/api/v1/audit-log", () =>
          HttpResponse.json({
            ...EMPTY_PAGE,
            total: 1,
            items: [
              {
                id: "a2",
                organization_id: "o1",
                user_id: "u1",
                user_email: "admin@example.com",
                action: "UPDATE",
                target_type: "module",
                target_id: "o1",
                snapshot: {
                  name: "approvals",
                  before: { allow_admin_self_approve: false },
                  after: { allow_admin_self_approve: true },
                },
                reason: null,
                meta_data: null,
                created_at: "2026-08-20T10:00:00Z",
              },
            ],
          }),
        ),
        http.get("/api/v1/modules/approvals/settings", () =>
          HttpResponse.json({
            settings: { allow_admin_self_approve: false },
            settings_schema: {
              type: "object",
              properties: {
                allow_admin_self_approve: {
                  type: "boolean",
                  default: false,
                  title_key: "approvals:settings.allowAdminSelfApprove",
                },
              },
            },
          }),
        ),
      );

      renderPage();

      const lines = await screen.findAllByText((_, element) => {
        return (
          element?.tagName === "DIV" &&
          (element as HTMLElement).textContent ===
            "Administrator może zatwierdzać własne wnioski: Nie → Tak"
        );
      });
      expect(lines.length).toBeGreaterThanOrEqual(1);
      // The tidied key is not the answer, on either variant of the row.
      expect(screen.queryByText(/Allow admin self approve/)).toBeNull();
    });
  });

  it("says nothing about fields that hold the same value on both sides", async () => {
    // Entries written before the snapshot was narrowed to the actual change
    // still list every field the form posted. Printing `X → X` for each of
    // them is how the one field that moved became unfindable.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a2",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "item",
              target_id: "i1",
              snapshot: {
                name: "Canned peas",
                before: { name: "Canned peas", quantity: 1 },
                after: { name: "Canned peas", quantity: 3 },
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("Quantity:")).toBeInTheDocument();
    expect(screen.getByText(/1 → 3/)).toBeInTheDocument();
    expect(screen.queryByText(/Canned peas → Canned peas/)).toBeNull();
  });

  it("says what a product was created with instead of a dash", async () => {
    // A CREATE entry has no before/after, so the Detail column rendered "—"
    // and the one question a journal should answer — with what did this
    // record come into the world — had no answer on the page.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a3",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "CREATE",
              target_type: "item",
              target_id: "i3",
              snapshot: {
                name: "Journal Milk",
                brand: null,
                quantity: 4,
                storage_location_id: "4c3d90a5-0000-0000-0000-000000000000",
                category_id: null,
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-27T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("Quantity:")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Location:")).toBeInTheDocument();
    expect(screen.getByText("4c3d90a5")).toBeInTheDocument();
    // The name is the Target column's job, so it is not also a change line.
    expect(screen.queryByText("Name:")).toBeNull();
  });

  it("names a document by its number, not by eight characters of its id", async () => {
    // A document is known by its number and writes it under `number`; the
    // page read `name` and nothing else, so every entry about a document —
    // including the one an auditor filters for — showed a UUID fragment.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a9",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "CREATE",
              target_type: "document",
              target_id: "cac73194-0000-0000-0000-000000000000",
              snapshot: { number: "IN/2026/009", status: "DRAFT" },
              reason: null,
              meta_data: null,
              created_at: "2026-09-02T20:50:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("IN/2026/009")).toBeInTheDocument();
  });

  it("exports the number as the target's label too", async () => {
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a10",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "document",
              target_id: "cac73194-0000-0000-0000-000000000000",
              snapshot: { number: "IN/2026/009", status: "CONFIRMED" },
              reason: null,
              meta_data: null,
              created_at: "2026-09-02T20:52:00Z",
            },
          ],
        }),
      ),
    );
    const csv = await captureCsv(async () => {
      renderPage();
      await screen.findByText("IN/2026/009");
      await exportCsv();
    });

    expect(csv).toContain("IN/2026/009");
  });

  it("names the changed paths inside a document, not the document twice", async () => {
    // One row took half a screen: a product's nutrition data from a food
    // database, printed whole before the arrow and whole after it.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a4",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "item",
              target_id: "i4",
              snapshot: {
                name: "Minced beef",
                before: {
                  meta_data: {
                    nutrition: { fat: 1.7999999523162842, carbs: 20 },
                    categories: ["meat", "fresh"],
                  },
                },
                after: {
                  meta_data: {
                    nutrition: { fat: 2.1, carbs: 20 },
                    categories: ["meat", "fresh"],
                  },
                },
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-27T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("Additional data › Nutrition › fat:"),
    ).toBeInTheDocument();
    // Rounded: eighteen digits of a 32-bit float artefact is not a figure
    // anybody recorded.
    expect(screen.getByText("1.8 → 2.1")).toBeInTheDocument();
    // The parts that did not move are not on the row at all.
    expect(screen.queryByText(/carbs/)).toBeNull();
    expect(screen.queryByText(/categories/)).toBeNull();
  });

  it("keeps a long change list short until the reader asks for it", async () => {
    const before: Record<string, number> = {};
    const after: Record<string, number> = {};
    for (let i = 0; i < 6; i++) {
      before[`field_${i}`] = i;
      after[`field_${i}`] = i + 1;
    }
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a5",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "item",
              target_id: "i5",
              snapshot: { name: "Wide record", before, after },
              reason: null,
              meta_data: null,
              created_at: "2026-08-27T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("field_0:")).toBeInTheDocument();
    expect(screen.getByText("field_1:")).toBeInTheDocument();
    expect(screen.queryByText("field_5:")).toBeNull();

    await userEvent.click(
      screen.getByRole("button", { name: /show the whole change/i }),
    );

    expect(screen.getByText("field_5:")).toBeInTheDocument();
  });

  it("exports the change in full, whatever the row shows", async () => {
    // Shortening is how the row reads, not what the journal holds.
    const snapshot = {
      name: "Minced beef",
      before: { meta_data: { nutrition: { fat: 1.7999999523162842 } } },
      after: { meta_data: { nutrition: { fat: 2.1 } } },
    };
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a6",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "item",
              target_id: "i6",
              snapshot,
              reason: null,
              meta_data: null,
              created_at: "2026-08-27T10:00:00Z",
            },
          ],
        }),
      ),
    );
    const csv = await captureCsv(async () => {
      renderPage();
      await screen.findByText("Additional data › Nutrition › fat:");
      await exportCsv();
    });

    expect(csv).toContain("1.7999999523162842");
  });
  it("puts a machine reason into words the reader can read", async () => {
    // The reason column holds two kinds of value: a note somebody typed, and
    // a key the code writes when stock moves on its own. Only the deletion
    // reasons had labels, so every entry a document or a cooking session
    // wrote showed its key -- `recipe_picking`, `document_execution` -- in
    // all five languages.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 2,
          items: [
            {
              id: "r1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "cook@example.com",
              action: "QUANTITY_CHANGE",
              target_type: "item",
              target_id: "i1",
              snapshot: { name: "Flour" },
              reason: "recipe_picking",
              meta_data: null,
              created_at: "2026-08-27T10:00:00Z",
            },
            {
              id: "r2",
              organization_id: "o1",
              user_id: "u1",
              user_email: "cook@example.com",
              action: "UPDATE",
              target_type: "approval_request",
              target_id: "a1",
              snapshot: { decision: "REJECTED" },
              reason: "The supplier changed the price list",
              meta_data: null,
              created_at: "2026-08-27T11:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("Cooking \u2014 ingredients taken"),
    ).toBeInTheDocument();
    expect(screen.queryByText("recipe_picking")).not.toBeInTheDocument();
    // A note somebody typed is not a key, so it still shows verbatim.
    expect(
      screen.getByText("The supplier changed the price list"),
    ).toBeInTheDocument();
    expect(screen.getByText("Approval request")).toBeInTheDocument();
  });

  it("names the stock reasons the dialogs write, USED included", async () => {
    // The reason column used to map CONSUMED while the quick-use flow
    // writes USED — so the row about eating the product carried the raw
    // code in the middle of the column the organization accounts on.
    // Every reason a dialog offers has a word here.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 2,
          items: [
            {
              id: "r3",
              organization_id: "o1",
              user_id: "u1",
              user_email: "cook@example.com",
              action: "USE",
              target_type: "item",
              target_id: "i1",
              snapshot: { name: "Yogurt" },
              reason: "USED",
              meta_data: null,
              created_at: "2026-08-27T12:00:00Z",
            },
            {
              id: "r4",
              organization_id: "o1",
              user_id: "u1",
              user_email: "cook@example.com",
              action: "DISPOSE",
              target_type: "item",
              target_id: "i2",
              snapshot: { name: "Lettuce" },
              reason: "DISPOSED",
              meta_data: null,
              created_at: "2026-08-27T12:05:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(await screen.findByText("Used")).toBeInTheDocument();
    expect(screen.queryByText("USED")).not.toBeInTheDocument();
    expect(screen.getByText("Disposed")).toBeInTheDocument();
    expect(screen.queryByText("DISPOSED")).not.toBeInTheDocument();
  });

  it("shows the numbers and the reason when a correction carries both", async () => {
    // The Detail column was an either/or — the stock take's
    // correction answered "what changed" (5 → 4) but dropped the why, and
    // the code for what the counter found sat in meta_data unseen. The
    // journal is the last instance of "why are the numbers what they are".
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a9",
              organization_id: "o1",
              user_id: "u1",
              user_email: "counter@example.com",
              action: "UPDATE",
              target_type: "item",
              target_id: "i1",
              snapshot: {
                name: "Yogurt",
                before: { quantity: "5.000" },
                after: { quantity: "4.000" },
              },
              reason: "stock_take_adjustment",
              meta_data: {
                stock_take_id: "st-1",
                discrepancy_reason_code: "LOSS",
              },
              created_at: "2026-09-01T12:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    // What changed, why the write happened, and what the count found —
    // all three in one cell.
    expect(await screen.findByText("Quantity:")).toBeInTheDocument();
    // The store's scale is not the reader's: "5.000 → 4.000" printed one
    // number as typed and the other as the Decimal column serialised it.
    expect(screen.getByText(/5 → 4/)).toBeInTheDocument();
    expect(screen.getByText("Stock take correction")).toBeInTheDocument();
    expect(screen.getByText("Lost or taken")).toBeInTheDocument();
  });

  it("names the document a quantity change came from", async () => {
    // The number sat in meta_data from the day the executors started
    // writing one; the screen read the change list and the reason and
    // stopped, so "Document execution" answered that something else wrote
    // the change and nothing about which document to look up.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "d1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "QUANTITY_CHANGE",
              target_type: "item",
              target_id: "i1",
              snapshot: {
                name: "Coffee Beans",
                before: { quantity: "18.000" },
                after: { quantity: "0.000" },
              },
              reason: "document_execution",
              meta_data: {
                document_type: "OUT",
                document_number: "OUT/2026/003",
                source_document_id: "8f2a1111-2222-3333-4444-555555555555",
              },
              created_at: "2026-09-02T20:50:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    const numbers = await screen.findAllByText(/OUT\/2026\/003/);
    expect(numbers.length).toBeGreaterThanOrEqual(1);
    // The two sides of the pair read in the reader's numbers, not in the
    // store's scale: the row says 18 → 0, one spelling on both sides.
    expect(screen.getByText(/18 → 0/)).toBeInTheDocument();
  });

  it("keeps the reason-only entry reading as it did", async () => {
    // The fix is a sum, not a swap: an entry with no snapshot still shows
    // just its reason, with no dash above it.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a10",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "organization",
              target_id: "o1",
              snapshot: null,
              reason: "stock_take_adjustment",
              meta_data: null,
              created_at: "2026-09-01T12:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    expect(
      await screen.findByText("Stock take correction"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Quantity:")).not.toBeInTheDocument();
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });
});

/**
 * The journal wrote the key's owner and nothing else, so an act performed by
 * an API key read exactly like one performed at the screen: same
 * `user_email`, no `meta_data`. Revoking a key is what makes that expensive —
 * the key leaves the list of keys, and without its prefix in the entry there
 * is nothing left to ask what it did.
 */
describe("AuditLogPage — a key's work", () => {
  /** One entry a key wrote and one the same person wrote by hand. */
  const TWO_ENTRIES = {
    ...EMPTY_PAGE,
    total: 2,
    items: [
      {
        id: "k1",
        organization_id: "o1",
        user_id: "u1",
        user_email: "qa-one@example.com",
        action: "CREATE",
        target_type: "item",
        target_id: "i1",
        snapshot: { name: "Beeswax pellets" },
        reason: null,
        meta_data: {
          actor: { type: "api_key", key_prefix: "inv_live_b3be8b5830a" },
        },
        created_at: "2026-08-28T10:00:00Z",
      },
      {
        id: "k2",
        organization_id: "o1",
        user_id: "u1",
        user_email: "qa-one@example.com",
        action: "CREATE",
        target_type: "item",
        target_id: "i2",
        snapshot: { name: "Beeswax pellets" },
        reason: null,
        meta_data: null,
        created_at: "2026-08-28T10:05:00Z",
      },
    ],
  };

  beforeEach(() => {
    server.use(
      http.get("/api/v1/audit-log", () => HttpResponse.json(TWO_ENTRIES)),
      http.get("/api/v1/audit-log/target-types", () => HttpResponse.json([])),
    );
  });

  it("asks the API for a key's entries when the reader asks for them", async () => {
    const asked: Array<string | null> = [];
    server.use(
      http.get("/api/v1/audit-log", ({ request }) => {
        asked.push(new URL(request.url).searchParams.get("actor"));
        return HttpResponse.json(TWO_ENTRIES);
      }),
    );

    renderPage();
    await userEvent.selectOptions(
      await screen.findByLabelText("Actor"),
      "api_key",
    );

    await waitFor(() => expect(asked[asked.length - 1]).toBe("api_key"));
    // "Everyone" is the default, so the first read carried no filter at all.
    expect(asked[0]).toBeNull();
  });

  it("names the key that acted, and only on the row a key wrote", async () => {
    renderPage();

    expect(await screen.findByText("inv_live_b3be8b5830a")).toBeInTheDocument();
    // Both rows are the same person's; one of them is a machine's.
    expect(screen.getAllByText("qa-one@example.com")).toHaveLength(2);
    expect(screen.getAllByText("API key")).toHaveLength(1);
  });

  it("keeps the key in the file the auditor takes away", async () => {
    const csv = await captureCsv(async () => {
      renderPage();
      await screen.findByText("inv_live_b3be8b5830a");
      await exportCsv();
    });

    expect(csv).toContain("inv_live_b3be8b5830a");
  });
});

/**
 * The export's name is a day, and it is the reader who reads it. Built
 * through `toISOString()` it named the file after the UTC day.
 */
describe("AuditLogPage — the day in the export filename", () => {
  const ONE_ENTRY = {
    ...EMPTY_PAGE,
    total: 1,
    items: [
      {
        id: "a1",
        organization_id: "o1",
        user_id: "u1",
        user_email: "admin@example.com",
        action: "CREATE",
        target_type: "item",
        target_id: "i1",
        snapshot: { name: "Beeswax pellets" },
        reason: null,
        meta_data: null,
        created_at: "2026-08-28T10:00:00Z",
      },
    ],
  };

  beforeEach(() => {
    server.use(
      http.get("/api/v1/audit-log", () => HttpResponse.json(ONE_ENTRY)),
      http.get("/api/v1/audit-log/target-types", () => HttpResponse.json([])),
    );
  });

  it("names the file after the reader's own day", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /export|csv/i })).toBeEnabled(),
    );

    const originalTZ = process.env.TZ;
    process.env.TZ = "Europe/Warsaw";
    vi.useFakeTimers();
    // 00:30 on 11 September 2026 local is still 22:30 on the 10th in UTC.
    vi.setSystemTime(new Date(2026, 8, 11, 0, 30));

    let filename = "";
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        filename = this.download;
      });
    const originalCreateObjectUrl = globalThis.URL.createObjectURL;
    const originalRevokeObjectUrl = globalThis.URL.revokeObjectURL;
    globalThis.URL.createObjectURL = () => "blob:audit";
    globalThis.URL.revokeObjectURL = () => {};
    try {
      fireEvent.click(screen.getByRole("button", { name: /export|csv/i }));

      expect(filename).toBe("audit-log-2026-09-11.csv");
    } finally {
      clickSpy.mockRestore();
      globalThis.URL.createObjectURL = originalCreateObjectUrl;
      globalThis.URL.revokeObjectURL = originalRevokeObjectUrl;
      vi.useRealTimers();
      process.env.TZ = originalTZ;
    }
  });
});

/**
 * Below md the log is a list of cards, not a five-column table in a scroller.
 * Measured at 390px: 391 of the table's 755 pixels were off-screen — "Target"
 * and "Details", which is the answer this page is opened for — and "Action"
 * broke mid-word. An entry reads whole or not at all.
 */
describe("AuditLogPage — on a phone", () => {
  // Captured in the hook, not at collection time: the shared matchMedia mock
  // is installed by the MSW setup's `beforeAll`, which runs after this file
  // is collected — snapshotting it here restored `undefined` instead, and
  // every test declared after this block asked a function that was not there.
  let originalMatchMedia: typeof window.matchMedia;

  beforeEach(() => {
    originalMatchMedia = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("max-width"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    window.matchMedia = originalMatchMedia;
  });

  it("says who, when, what and on what without a table to scroll", async () => {
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "a1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "admin@example.com",
              action: "UPDATE",
              target_type: "document",
              target_id: "11111111-2222-3333-4444-555555555555",
              snapshot: {
                number: "IN/2026/009",
                before: { quantity: 1 },
                after: { quantity: 3 },
              },
              reason: null,
              meta_data: null,
              created_at: "2026-08-20T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    const card = await screen.findByTestId("audit-log-card");
    expect(screen.queryByRole("table")).toBeNull();
    // who, what, on what, and what changed — all four in the one card.
    expect(within(card).getByText("admin@example.com")).toBeInTheDocument();
    expect(within(card).getByText("Update")).toBeInTheDocument();
    expect(within(card).getByText("IN/2026/009")).toBeInTheDocument();
    expect(within(card).getByText(/1 → 3/)).toBeInTheDocument();
  });

  it("says on the card which key acted", async () => {
    // The card is a second render branch of the same row, and a reader on a
    // phone is as likely to be the administrator who revoked the key.
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({
          ...EMPTY_PAGE,
          total: 1,
          items: [
            {
              id: "k1",
              organization_id: "o1",
              user_id: "u1",
              user_email: "qa-one@example.com",
              action: "CREATE",
              target_type: "item",
              target_id: "i1",
              snapshot: { name: "Beeswax pellets" },
              reason: null,
              meta_data: {
                actor: { type: "api_key", key_prefix: "inv_live_b3be8b5830a" },
              },
              created_at: "2026-08-28T10:00:00Z",
            },
          ],
        }),
      ),
    );

    renderPage();

    const card = await screen.findByTestId("audit-log-card");
    expect(within(card).getByText("inv_live_b3be8b5830a")).toBeInTheDocument();
    expect(within(card).getByText("API key")).toBeInTheDocument();
    // The key's kind is labelled, not printed as the machine's own word for
    // itself — `api_key` is a value in the column, not a word in five
    // languages.
    expect(within(card).queryByText("api_key")).toBeNull();
  });
});

/**
 * A name on a journal row belongs to the row it was written for.
 *
 * The page used to build one map from every row it was showing — id to the
 * row's own identity — and hand it to every other row. A module switched on
 * puts the *organization's* id in its target column and the *module's* name
 * in its snapshot, so on a page holding both, a product's row read
 * `Organization: stats`: the name of a module, on a row about a product, in
 * a shape the reader has no way to doubt. And because the map was whatever
 * happened to be on the page, the same row read correctly under one filter
 * and not under another.
 */
describe("AuditLogPage — the name on a row belongs to that row", () => {
  const ORG_ID = "3f2a1c48-5b0e-4d6f-9a21-8c7d5e4f3b2a";
  const ITEM_ID = "9c1d2e3f-4a5b-6c7d-8e9f-0a1b2c3d4e5f";

  /** A module switched on: the organization's id in the target column, the
   *  module's name as the identity — the shape that poisoned the map. */
  const MODULE_TOGGLE = {
    id: "m1",
    organization_id: ORG_ID,
    user_id: "u1",
    user_email: "admin@example.com",
    action: "UPDATE",
    target_type: "module",
    target_id: ORG_ID,
    snapshot: {
      name: "stats",
      before: { enabled: false },
      after: { enabled: true },
    },
    reason: null,
    meta_data: null,
    created_at: "2026-09-20T11:15:05Z",
  };

  /** An archived product, purged: the snapshot names the record it was about
   *  by id, which is what the writer has always written there. */
  const ITEM_PURGE = {
    id: "i1",
    organization_id: ORG_ID,
    user_id: "u1",
    user_email: "admin@example.com",
    action: "PURGE",
    target_type: "item",
    target_id: ITEM_ID,
    snapshot: {
      name: "REV Steak",
      organization_id: ORG_ID,
      is_deleted: true,
    },
    reason: "gone off",
    meta_data: null,
    created_at: "2026-09-20T12:15:05Z",
  };

  const THE_ORGANIZATION = { id: ORG_ID, name: "Katerina Logistics" };

  function serve(rows: unknown[]) {
    server.use(
      http.get("/api/v1/audit-log", () =>
        HttpResponse.json({ ...EMPTY_PAGE, total: rows.length, items: rows }),
      ),
      http.get("/api/v1/audit-log/target-types", () =>
        HttpResponse.json(["item", "module"]),
      ),
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json(THE_ORGANIZATION),
      ),
    );
  }

  const itemRow = async () => {
    const cell = await screen.findByText("REV Steak");
    const row = cell.closest("tr");
    expect(row).not.toBeNull();
    return row as HTMLElement;
  };

  it("does not read a module's name into the organization its neighbour names", async () => {
    serve([MODULE_TOGGLE, ITEM_PURGE]);

    renderPage();

    const row = within(await itemRow());
    expect(row.queryByText("stats")).toBeNull();
    expect(await row.findByText("Katerina Logistics")).toBeInTheDocument();
  });

  it("reads the organization's name when no module row is on the page", async () => {
    // The same entry, under a filter that leaves the module's row out. What
    // the reader sees about the product cannot be decided by what else the
    // page happens to hold.
    serve([ITEM_PURGE]);

    renderPage();

    const row = within(await itemRow());
    expect(await row.findByText("Katerina Logistics")).toBeInTheDocument();
  });
});

/**
 * The webhook journal's three hard rows: an act of the system, the same act
 * in its older spelling, and a person's answer to it.
 *
 * A cut-off by the circuit breaker has no account to name, and "Unknown
 * user" read like the act of somebody whose account was since deleted — the
 * breaker is the actor. Its reason arrived as the raw code; a reactivation
 * read as a plain update over a channel that was never off.
 */
const BREAKER_ENTRY = {
  id: "e2",
  organization_id: "org-1",
  user_id: null,
  user_email: null,
  action: "UPDATE",
  target_type: "webhook_endpoint",
  target_id: "wh-1",
  snapshot: { name: "Home Assistant", url: "https://ha.example/hook" },
  reason: "circuit_breaker",
  meta_data: {
    actor: { type: "system" },
    auto_disabled: true,
    consecutive_failures: 10,
  },
  created_at: "2026-10-01T10:00:00Z",
};

const LEGACY_BREAKER_ENTRY = {
  ...BREAKER_ENTRY,
  id: "e3",
  meta_data: { auto_disabled: true, consecutive_failures: 10 },
};

const REACTIVATION_ENTRY = {
  id: "e4",
  organization_id: "org-1",
  user_id: "u1",
  user_email: "qa-many@example.com",
  action: "UPDATE",
  target_type: "webhook_endpoint",
  target_id: "wh-1",
  snapshot: { name: "Home Assistant", url: "https://ha.example/hook" },
  reason: null,
  meta_data: { reactivated_after_circuit_breaker: true },
  created_at: "2026-10-01T11:00:00Z",
};

const SECRET_EDIT_ENTRY = {
  id: "e5",
  organization_id: "org-1",
  user_id: "u1",
  user_email: "qa-many@example.com",
  action: "UPDATE",
  target_type: "webhook_endpoint",
  target_id: "wh-1",
  snapshot: {
    name: "Home Assistant",
    url: "https://ha.example/hook",
    before: {},
    after: {},
    fields: ["secret"],
  },
  reason: null,
  meta_data: null,
  created_at: "2026-10-01T12:00:00Z",
};

function stubAudit(...items: unknown[]) {
  server.use(
    http.get("/api/v1/audit-log", () =>
      HttpResponse.json({
        items,
        total: items.length,
        limit: 100,
        offset: 0,
        has_more: false,
      }),
    ),
    http.get("/api/v1/audit-log/target-types", () => HttpResponse.json([])),
  );
}

describe("AuditLogPage — the breaker's rows name their actor", () => {
  it("says System, not Unknown user, for a cut-off by the safety switch", async () => {
    stubAudit(BREAKER_ENTRY);
    renderPage();

    expect(await screen.findAllByText("System")).not.toHaveLength(0);
    expect(screen.queryByText("Unknown user")).not.toBeInTheDocument();
  });

  it("reads the older breaker rows the same way, by their mark alone", async () => {
    stubAudit(LEGACY_BREAKER_ENTRY);
    renderPage();

    expect(await screen.findAllByText("System")).not.toHaveLength(0);
    expect(screen.queryByText("Unknown user")).not.toBeInTheDocument();
  });

  it("translates the breaker's reason instead of printing the code", async () => {
    stubAudit(BREAKER_ENTRY);
    renderPage();

    const reason = await screen.findAllByText(
      "Disabled by the circuit breaker after repeated delivery failures",
    );
    expect(reason.length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("circuit_breaker")).not.toBeInTheDocument();
  });

  it("reads a reactivation as an answer to the cut-off, in Polish", async () => {
    await withLanguage("pl", async () => {
      stubAudit(REACTIVATION_ENTRY);
      renderPage();

      const sentence = await screen.findAllByText(
        "Wznowione po odcięciu przez bezpiecznik",
      );
      expect(sentence.length).toBeGreaterThanOrEqual(1);
    });
  });

  it("names the rotated secret by its word, never by a value", async () => {
    stubAudit(SECRET_EDIT_ENTRY);
    renderPage();

    const fact = await screen.findAllByText("Signing secret");
    expect(fact.length).toBeGreaterThanOrEqual(1);
  });
});
