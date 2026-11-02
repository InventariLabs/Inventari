import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import ApiKeysPage from "../pages/ApiKeysPage";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const header = vi.hoisted(() => ({
  setHeader: vi.fn<(config: { actions?: ReactNode }) => void>(),
}));

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: header.setHeader }),
}));

const key = {
  id: "key-1",
  name: "Home Assistant",
  key_prefix: "inv_live_abcd",
  is_active: true,
  last_used_at: null,
  expires_at: null,
  created_at: "2026-08-01T10:00:00Z",
  created_by_email: "admin@example.com",
  permissions: ["items:read", "locations:read"],
  scopes: [],
};

/** Comfortably outside any clock skew this test could meet. */
const PAST = "2026-01-01T00:00:00Z";
const FUTURE = "2099-01-01T00:00:00Z";

// The shape the endpoint really answers with: administering the
// organization is withheld from a key, not granted to it.
const capabilities = {
  catalog: [
    {
      key: "items:read",
      label_key: "permissions:system.items_read",
      description_key: null,
    },
    {
      key: "locations:read",
      label_key: "permissions:system.storages_read",
      description_key: null,
    },
    {
      key: "org:members:write",
      label_key: "permissions:system.org_members_write",
      description_key: null,
    },
  ],
  grantable: ["items:read", "locations:read"],
  default_permissions: ["items:read", "locations:read"],
  withheld_permissions: ["org:members:write", "org:settings:write"],
  admin_areas_blocked: true,
  header: "X-API-Key",
  scopes: [{ name: "printing", permissions: ["printing:agent"] }],
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ApiKeysPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ApiKeysPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([key]))),
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities),
      ),
    );
  });

  it("says what no key may carry, including the part nobody expects", async () => {
    // It used to describe org:settings:write as "change organization
    // settings", a thing too vague to act on; then as the SKU naming alone,
    // which was two of the four areas behind it. The route table names all
    // four, and no key may hold it, so the line has to be worth reading on
    // the side that says what a key does NOT get.
    renderPage();

    expect(await screen.findByText("Never on a key")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Administer the organization: AI connections, equipment document templates, the organization-wide SKU naming and the API key register",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Manage members")).toBeInTheDocument();
  });

  it("says administration is closed, and names the one list that leaks", async () => {
    renderPage();

    expect(
      await screen.findByText(/roles, invitations, modules/),
    ).toBeInTheDocument();
    // A leaked key is also a leaked team roster: the member list answers 200
    // with names, e-mails and roles to a key that reads the organization.
    // The sentence promising that everything administrative is closed must
    // carry the exception.
    expect(
      screen.getByText(/can read every member's name/),
    ).toBeInTheDocument();
  });

  it("shows each key's own permissions beside it", async () => {
    renderPage();

    // Both breakpoints render, so the line appears twice.
    expect(
      await screen.findAllByText(
        "Read products and stock levels, Read locations",
      ),
    ).toHaveLength(2);
  });

  it("says the card could not be read instead of leaving it out", async () => {
    // The card rendered nothing when the read failed: the page then said
    // nothing at all about what a key may do, as if there were no answer.
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderPage();

    expect(
      await screen.findByText(/what a key can do could not be loaded/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeVisible();
  });

  it("names the key's own header, and says the Bearer form is going", async () => {
    renderPage();

    expect(
      await screen.findByText(/travels in the X-API-Key header/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Deprecation header/)).toBeInTheDocument();
    expect(
      screen.getByText(/curl -H 'X-API-Key: inv_live_…'/),
    ).toBeInTheDocument();
  });

  it("shows who issued the key", async () => {
    renderPage();

    await waitFor(() =>
      expect(screen.getAllByText("admin@example.com").length).toBeGreaterThan(
        0,
      ),
    );
  });

  it("marks a key confined to printing", async () => {
    server.use(
      http.get("/api/v1/api-keys", () =>
        HttpResponse.json(
          onePage([
            { ...key, scopes: ["printing"], permissions: ["printing:agent"] },
          ]),
        ),
      ),
    );
    renderPage();

    await waitFor(() =>
      expect(screen.getAllByText("Printing only").length).toBeGreaterThan(0),
    );
  });

  it("distinguishes a key never used from one that never expires", async () => {
    // Both columns said "Never", which answers two different questions with
    // one word.
    renderPage();

    expect(await screen.findAllByText("Not yet used")).not.toHaveLength(0);
    expect(screen.getAllByText("Does not expire")).not.toHaveLength(0);
  });

  it("marks a key whose expiry has passed, and puts it after the live ones", async () => {
    // Measured on five keys, one of them lapsed: `row.className` identical
    // across all five, no badge anywhere, and the only difference was a date
    // in the EXPIRES column the reader had to compare against today. The
    // LAST USED column said "Not yet used" for every one of them, so it did
    // not help either.
    server.use(
      http.get("/api/v1/api-keys", () =>
        HttpResponse.json(
          onePage([
            { ...key, id: "dead", name: "Old importer", expires_at: PAST },
            { ...key, id: "live", name: "Home Assistant", expires_at: FUTURE },
          ]),
        ),
      ),
    );
    renderPage();

    const rows = await screen.findAllByTestId("api-key-row");
    // Both breakpoints render, so each key appears twice; the live one still
    // comes first in each list.
    expect(rows[0]).toHaveTextContent("Home Assistant");
    expect(rows[0]).not.toHaveTextContent("Expired");
    expect(rows[1]).toHaveTextContent("Old importer");
    expect(rows[1]).toHaveTextContent("Expired");
  });

  it("leaves a key that never expires unmarked", async () => {
    renderPage();

    await screen.findAllByTestId("api-key-row");
    expect(screen.queryByText("Expired")).toBeNull();
  });

  it("says where a revoked key leaves its trace", async () => {
    // The list holds active keys only: revoking made the row vanish, which
    // is also what a key that never existed looks like.
    renderPage();

    expect(
      await screen.findByText(/recorded in the audit log/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open the audit log" }),
    ).toHaveAttribute("href", "/settings/audit-log");
  });
});

/**
 * The key that guards this screen is not the module's own.
 *
 * `api_keys` mounts `require_permission(ORG_SETTINGS_WRITE)` rather than the
 * usual read/write pair, because issuing a key that can act as the
 * organization is an organization setting. A page asking `api_keys:write`
 * would hide the buttons from everyone and show them to nobody.
 */
describe("ApiKeysPage — issuing a key is an organization setting", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([key]))),
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities),
      ),
    );
  });

  afterEach(() => signOut());

  it("offers revoking to an account holding org:settings:write", async () => {
    signInWith(["org:read", "org:settings:write"]);
    renderPage();

    // Rendered twice: a card list for phones and a table for wider screens.
    expect((await screen.findAllByText("Home Assistant")).length).toBe(2);
    expect(
      (await screen.findAllByTestId("api-key-revoke-btn")).length,
    ).toBeGreaterThan(0);
    expect(
      screen.queryByText(/you can view this, not change it/i),
    ).not.toBeInTheDocument();
  });

  it("offers the first key from the empty state as an outline, since the header owns the filled one", async () => {
    signInWith(["org:read", "org:settings:write"]);
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([]))),
    );
    renderPage();

    const entry = await screen.findByRole("button", {
      name: /generate new key/i,
    });
    expect(entry.className).not.toContain("text-white");
  });

  it("says why, and offers no revoke, without it", async () => {
    signInWith(["org:read"]);
    renderPage();

    expect((await screen.findAllByText("Home Assistant")).length).toBe(2);
    expect(
      await screen.findByText(/you can view this, not change it/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("api-key-revoke-btn")).not.toBeInTheDocument();
  });
});

describe("ApiKeysPage — acting on keys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([key]))),
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities),
      ),
    );
    signInWith(["org:read", "org:settings:write"]);
  });

  afterEach(() => signOut());

  it("offers retrying a failed list, and shows the keys once the read succeeds", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/api-keys", () => {
        calls += 1;
        return calls === 1
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json(onePage([key]));
      }),
    );
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: /try again/i }),
    );

    expect((await screen.findAllByText("Home Assistant")).length).toBe(2);
    expect(calls).toBe(2);
  });

  it("opens the issuing sheet from the header's button", async () => {
    renderPage();
    await screen.findAllByText("Home Assistant");
    const actions = header.setHeader.mock.calls
      .map(([config]) => config.actions)
      .filter(Boolean)
      .at(-1);
    render(<>{actions}</>);

    await userEvent.click(
      screen.getByRole("button", { name: "Generate New Key" }),
    );

    expect(await screen.findByText("Generate Key")).toBeInTheDocument();
  });

  it("issues a key from the empty state, shows it once, and closes on Close", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([]))),
      http.post("/api/v1/api-keys", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...key, raw_key: "inv_live_SECRET123" });
      }),
    );
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: /generate new key/i }),
    );
    await userEvent.type(
      await screen.findByPlaceholderText(/home assistant/i),
      "Backup script",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /^generate key$/i }),
    );

    expect(await screen.findByText("inv_live_SECRET123")).toBeInTheDocument();
    expect(sent).toMatchObject({ name: "Backup script", expires_at: null });

    await userEvent.click(screen.getByTestId("api-key-dialog-close"));
    expect(screen.queryByText("inv_live_SECRET123")).not.toBeInTheDocument();
  });

  it("tells the reader when the server refuses to issue the key", async () => {
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([]))),
      http.post("/api/v1/api-keys", () =>
        HttpResponse.json({ detail: "Key limit reached" }, { status: 400 }),
      ),
    );
    renderPage();

    await userEvent.click(
      await screen.findByRole("button", { name: /generate new key/i }),
    );
    await userEvent.type(
      await screen.findByPlaceholderText(/home assistant/i),
      "Backup script",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /^generate key$/i }),
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.queryByText("API Key Generated")).not.toBeInTheDocument();
  });

  it("closes the issuing sheet on Cancel without sending anything", async () => {
    let posted = false;
    server.use(
      http.get("/api/v1/api-keys", () => HttpResponse.json(onePage([]))),
      http.post("/api/v1/api-keys", () => {
        posted = true;
        return HttpResponse.json({ ...key, raw_key: "x" });
      }),
    );
    renderPage();
    await userEvent.click(
      await screen.findByRole("button", { name: /generate new key/i }),
    );
    await screen.findByText("Generate Key");

    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() =>
      expect(screen.queryByText("Generate Key")).not.toBeInTheDocument(),
    );
    expect(posted).toBe(false);
  });

  it.each([
    ["the phone card", 0],
    ["the desktop table row", 1],
  ])(
    "revokes a key from %s only after confirming, then says so",
    async (_, index) => {
      const revoked: string[] = [];
      server.use(
        http.delete("/api/v1/api-keys/:id", ({ params }) => {
          revoked.push(String(params.id));
          return new HttpResponse(null, { status: 204 });
        }),
      );
      renderPage();

      await userEvent.click(
        (await screen.findAllByTestId("api-key-revoke-btn"))[index],
      );
      const dialog = await screen.findByRole("alertdialog");
      expect(revoked).toEqual([]);
      expect(dialog).toHaveTextContent('"Home Assistant"');
      await userEvent.click(
        within(dialog).getByRole("button", { name: "Revoke" }),
      );

      await waitFor(() => expect(toast.success).toHaveBeenCalled());
      expect(revoked).toEqual(["key-1"]);
      await waitFor(() =>
        expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
      );
    },
  );

  it("keeps the key and sends nothing when the revoke is cancelled", async () => {
    let deleted = false;
    server.use(
      http.delete("/api/v1/api-keys/:id", () => {
        deleted = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderPage();
    await userEvent.click(
      (await screen.findAllByTestId("api-key-revoke-btn"))[0],
    );
    const dialog = await screen.findByRole("alertdialog");

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(deleted).toBe(false);
  });

  it("reports a refused revoke instead of claiming the key was revoked", async () => {
    server.use(
      http.delete("/api/v1/api-keys/:id", () =>
        HttpResponse.json({ detail: "nope" }, { status: 500 }),
      ),
    );
    renderPage();
    await userEvent.click(
      (await screen.findAllByTestId("api-key-revoke-btn"))[0],
    );
    const dialog = await screen.findByRole("alertdialog");

    await userEvent.click(
      within(dialog).getByRole("button", { name: "Revoke" }),
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });
});
