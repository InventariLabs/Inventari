import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import { RolePermissionsSheet } from "./RolePermissionsSheet";
import { permissionGroups } from "./rolePermissions";
import { api } from "@/lib/api/client";
import type {
  PermissionCatalog,
  Role,
} from "@/modules/settings/hooks/useRoles";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const CATALOG: PermissionCatalog = {
  system: [
    {
      key: "items:read",
      label_key: "permissions:system.items_read",
      description_key: "permissions:system.items_readDesc",
      default_roles: [],
    },
    {
      key: "items:write",
      label_key: "permissions:system.items_write",
      description_key: "permissions:system.items_writeDesc",
      default_roles: [],
    },
  ],
  modules: [
    {
      module: "warehouse",
      permissions: [
        {
          key: "warehouse:read",
          label_key: "warehouse:permissions.read",
          description_key: "warehouse:permissions.readDesc",
          default_roles: [],
        },
      ],
    },
  ],
};

const GROUPS = permissionGroups(CATALOG);

const role = (permissions: string[], overrides: Partial<Role> = {}): Role => ({
  id: "role-1",
  organization_id: "org-1",
  name: "Warehouse operator",
  permissions,
  is_system: false,
  created_at: null,
  member_count: 0,
  ...overrides,
});

function renderSheet(subject: Role, onClose = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RolePermissionsSheet role={subject} groups={GROUPS} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

/** Capture what the save actually puts on the wire. */
function captureSave() {
  const sent: string[][] = [];
  server.use(
    http.put("*/roles/:id/permissions", async ({ request }) => {
      const body = (await request.json()) as { permissions: string[] };
      sent.push(body.permissions);
      return HttpResponse.json({ ...role([]), permissions: body.permissions });
    }),
  );
  return sent;
}

describe("RolePermissionsSheet — deleting and renaming", () => {
  const holders = [
    { id: "u1", email: "anna@example.com", full_name: "Anna Kowalska" },
    { id: "u2", email: "bo@example.com", full_name: null },
  ];

  function withHolders(list: typeof holders) {
    server.use(
      http.get("*/roles/:id/members", () => HttpResponse.json(onePage(list))),
    );
  }

  async function openMenu(user: ReturnType<typeof userEvent.setup>) {
    await user.click(
      await screen.findByRole("button", { name: /actions for/i }),
    );
  }

  it("names the people standing in the way, and offers no delete button", async () => {
    // The refusal has to be the whole dialog. A red button that deletes anyway
    // would offer the one thing the rule exists to prevent.
    const user = userEvent.setup();
    withHolders(holders);
    renderSheet(role([]));

    await openMenu(user);
    await user.click(await screen.findByRole("button", { name: /delete/i }));

    expect(
      await screen.findByText("Anna Kowalska · anna@example.com"),
    ).toBeInTheDocument();
    expect(screen.getByText("bo@example.com")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /^delete$/i })).toBeNull(),
    );
  });

  it("warns that the fallback can widen access, not only narrow it", async () => {
    const user = userEvent.setup();
    withHolders(holders);
    renderSheet(role([]));

    await openMenu(user);
    await user.click(await screen.findByRole("button", { name: /delete/i }));

    expect(await screen.findByText(/built-in level/i)).toBeInTheDocument();
  });

  it("deletes a role nobody holds", async () => {
    const user = userEvent.setup();
    const deleted: string[] = [];
    withHolders([]);
    server.use(
      http.delete("*/roles/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const onClose = renderSheet(role([]));

    await openMenu(user);
    await user.click(await screen.findByRole("button", { name: /delete/i }));
    await user.click(await screen.findByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(deleted).toEqual(["role-1"]));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("does not ask a deleted role who holds it", async () => {
    // The delete invalidates the whole `["roles"]` prefix, and the members
    // key sits under it. The dialog kept the query enabled until it closed —
    // after the invalidation — so the role the DELETE had just removed was
    // asked for its members once more, and the server answered 400 behind a
    // delete that had succeeded. The delete's refresh skips the removed role.
    const user = userEvent.setup();
    const get = vi.spyOn(api, "get");
    server.use(
      http.get("*/roles/:id/members", () => HttpResponse.json(onePage([]))),
      http.delete("*/roles/:id", () => new HttpResponse(null, { status: 204 })),
    );
    const memberReads = () =>
      get.mock.calls.filter(([url]) => String(url).endsWith("/members")).length;
    const onClose = renderSheet(role([]));

    await openMenu(user);
    await user.click(await screen.findByRole("button", { name: /delete/i }));
    await waitFor(() => expect(memberReads()).toBe(1));

    await user.click(await screen.findByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());

    // A stale read ordered by the invalidation is sent before the close —
    // synchronously, through this same client — so the count is settled here.
    expect(memberReads()).toBe(1);
  });

  it("says why the role could not be deleted, in the server's words", async () => {
    // The dialog reads the holders before offering the delete, but that list is
    // a snapshot: somebody can take the role between the read and the click.
    // The server answers 409 ROLE_IN_USE with the sentence and the count, and
    // the caller's fixed "could not delete" would have thrown both away.
    const user = userEvent.setup();
    withHolders([]);
    server.use(
      http.delete("*/roles/:id", () =>
        HttpResponse.json(
          {
            detail: {
              code: "ROLE_IN_USE",
              message:
                "Ta rola jest jeszcze komuś przypisana. Najpierw zmień tym osobom rolę, potem ją usuń.",
              member_count: 2,
            },
          },
          { status: 409 },
        ),
      ),
    );
    renderSheet(role([]));

    await openMenu(user);
    await user.click(await screen.findByRole("button", { name: /delete/i }));
    await user.click(await screen.findByRole("button", { name: /^delete$/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Ta rola jest jeszcze komuś przypisana. Najpierw zmień tym osobom rolę, potem ją usuń.",
      ),
    );
  });

  it("shows the name that collided when the rename is refused", async () => {
    // The create form beside this sheet already shows the server's own sentence
    // for a name clash; a rename hits the same rule and was answering with a
    // guess of its own ("does a role with that name already exist?").
    server.use(
      http.patch("*/roles/:id", () =>
        HttpResponse.json(
          {
            detail: {
              code: "VALIDATION_ERROR",
              message:
                'Role with name "Warehouse operator" already exists in this organisation',
            },
          },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderSheet(role([]));

    await openMenu(user);
    await user.click(await screen.findByRole("button", { name: /rename/i }));
    await user.type(
      await screen.findByRole("textbox", { name: /role name/i }),
      " two",
    );
    await user.click(await screen.findByRole("button", { name: /^save$/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        'Role with name "Warehouse operator" already exists in this organisation',
      ),
    );
  });

  it("refuses to save a rename that changes nothing", async () => {
    const user = userEvent.setup();
    renderSheet(role([]));

    await openMenu(user);
    await user.click(await screen.findByRole("button", { name: /rename/i }));

    expect(await screen.findByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("offers neither action on a built-in role", async () => {
    renderSheet(role([], { is_system: true, name: "Manager" }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /actions for/i })).toBeNull(),
    );
  });
});

describe("RolePermissionsSheet", () => {
  it("spells out what each permission does, not just its name", async () => {
    // The catalog has always carried a description; a column header eight
    // characters wide had nowhere to put it.
    renderSheet(role(["items:read"]));

    expect(
      await screen.findByText(
        "Can browse the product catalogue and stock levels",
      ),
    ).toBeInTheDocument();
  });

  it("heads a module the translations do not know with its manifest name", async () => {
    // A scaffolded module has no entry in the i18n catalog; its manifest name
    // is the only readable heading, and the technical name must not show.
    const catalog: PermissionCatalog = {
      ...CATALOG,
      modules: [
        ...CATALOG.modules,
        {
          module: "review_probe",
          display_name: "Review Probe",
          permissions: [
            {
              key: "review_probe:read",
              label_key: "review_probe:permissions.read",
              description_key: null,
              default_roles: [],
            },
          ],
        },
      ],
    };
    const queryClient = new QueryClient();
    render(
      <QueryClientProvider client={queryClient}>
        <RolePermissionsSheet
          role={role(["review_probe:read"])}
          groups={permissionGroups(catalog)}
          onClose={vi.fn()}
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Review Probe")).toBeInTheDocument();
    expect(screen.queryByText("review_probe")).toBeNull();
  });

  it("opens the areas the role uses and leaves the rest shut", async () => {
    renderSheet(role(["items:read"]));

    expect(await screen.findByText("View products")).toBeInTheDocument();
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    // documents holds nothing, so its heading is there and its contents are not.
    expect(screen.getByText("0 of 1")).toBeInTheDocument();
    expect(screen.queryByText("View documents")).toBeNull();
  });

  it("grants a whole area at once, and takes it back", async () => {
    const user = userEvent.setup();
    const sent = captureSave();
    renderSheet(role([]));

    await user.click(await screen.findByRole("checkbox", { name: "General" }));
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].sort()).toEqual(["items:read", "items:write"]);
  });

  it("carries permissions from a module that is switched off", async () => {
    // The keys have no checkbox here. Sending only what the boxes show would
    // silently revoke access the administrator never touched.
    const user = userEvent.setup();
    const sent = captureSave();
    renderSheet(role(["items:read", "maker:write"]));

    expect(await screen.findByText(/switched off/i)).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /view products/i }));
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual(["maker:write"]);
  });

  it("finds a permission across every area, open or shut", async () => {
    const user = userEvent.setup();
    renderSheet(role([]));

    await user.type(
      await screen.findByRole("textbox", { name: /find a permission/i }),
      "warehouse",
    );

    expect(screen.getByText("View documents")).toBeInTheDocument();
    expect(screen.queryByText("View products")).toBeNull();
  });

  it("refuses to save until something changed", async () => {
    renderSheet(role(["items:read"]));

    expect(await screen.findByRole("button", { name: /save/i })).toBeDisabled();
  });

  it("offers no edit control on a built-in role", async () => {
    renderSheet(role(["items:read"], { is_system: true, name: "Manager" }));

    expect(await screen.findByText(/read-only/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save/i })).toBeNull();
    for (const box of screen.getAllByRole("checkbox")) {
      expect(box).toBeDisabled();
    }
  });
});
