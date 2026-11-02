import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import OrganizationMembers from "./OrganizationMembers";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const members = {
  items: [
    {
      id: "member-1",
      email: "clerk@example.com",
      full_name: "Warehouse Clerk",
      role: "user",
    },
  ],
  total: 1,
  limit: 20,
  offset: 0,
};

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OrganizationMembers />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("OrganizationMembers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("*/organizations/my/members", () => HttpResponse.json(members)),
      http.get("*/roles", () => HttpResponse.json(onePage([]))),
    );
  });

  it("says the members could not be loaded instead of listing nobody", async () => {
    server.use(
      http.get(
        "*/organizations/my/members",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    signInWith(["admin:access"]);
    renderSettings();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
  });

  it("says the roles could not be loaded instead of offering no custom roles", async () => {
    server.use(
      http.get("*/roles", () => new HttpResponse(null, { status: 500 })),
    );
    signInWith(["admin:access"]);
    renderSettings();

    expect(await screen.findByText("Warehouse Clerk")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("keeps the identity full-width on the phone and the role control on its own line", async () => {
    // At 390 px a fixed 176 px role select left the identity column ~52 px:
    // name, address and role all truncated until two different accounts
    // looked identical. Below lg the row stacks — the identity gets the
    // whole line, the role control gets its own.
    server.use(
      http.get("*/organizations/my/members", () =>
        HttpResponse.json({
          items: [
            {
              id: "member-1",
              email: "clerk@example.com",
              full_name: "Warehouse Clerk",
              role: "user",
            },
            {
              id: "member-2",
              email: "clerk.supervisor@example.com",
              full_name: "Warehouse Supervisor",
              role: "manager",
            },
          ],
          total: 2,
          limit: 20,
          offset: 0,
        }),
      ),
    );
    signInWith(["admin:access"]);
    renderSettings();

    const clerk = await screen.findByText("clerk@example.com");
    const row = clerk.closest(".group");
    expect(row).not.toBeNull();
    expect(row).toHaveClass("flex-col");
    expect(row).toHaveClass("lg:flex-row");

    // The signed-in administrator's own row has no role control; the
    // supervisor's row carries it — on its own full-width line.
    const select = await screen.findByRole("combobox", {
      name: /Warehouse Supervisor/,
    });
    // The select's wrapper is the element that carries the width contract:
    // full width on its own line below md, fixed beside the identity above.
    const wrapper = (select as HTMLSelectElement).closest("div.w-full");
    expect(wrapper).not.toBeNull();
    expect(wrapper).toHaveClass("lg:w-44");

    // Two accounts sharing a prefix stay readable in full — nothing is
    // truncated into sameness.
    expect(screen.getByText("Warehouse Clerk")).toBeInTheDocument();
    expect(screen.getByText("Warehouse Supervisor")).toBeInTheDocument();
    expect(
      screen.getByText("clerk.supervisor@example.com"),
    ).toBeInTheDocument();
  });

  it("wraps a long address on the phone instead of cutting its ending", async () => {
    // Below lg the identity column is ~258 px wide: two company addresses that
    // differ only in their last label both clipped to the same
    // "magazyn.operacje.kierownik@dzial.firma.ex…". The line wraps there; from
    // md up, where the row is wide, it keeps the single clipped line.
    server.use(
      http.get("*/organizations/my/members", () =>
        HttpResponse.json({
          items: [
            {
              id: "member-1",
              email: "magazyn.operacje.kierownik@dzial.firma.example.com",
              full_name: "Manager One",
              role: "user",
            },
            {
              id: "member-2",
              email: "magazyn.operacje.kierownik@dzial.firma.example.org",
              full_name: "Manager Two",
              role: "user",
            },
          ],
          total: 2,
          limit: 20,
          offset: 0,
        }),
      ),
    );
    signInWith(["admin:access"]);
    renderSettings();

    for (const email of [
      "magazyn.operacje.kierownik@dzial.firma.example.com",
      "magazyn.operacje.kierownik@dzial.firma.example.org",
    ]) {
      const line = await screen.findByText(email);
      expect(line).toHaveClass("break-words");
      expect(line).not.toHaveClass("truncate");
      expect(line).toHaveClass("lg:truncate");
    }
  });

  it("lets an administrator make somebody a manager", async () => {
    // The role gates closing periods, the document profile and cancelling
    // purchase orders, and nothing in the product could grant it.
    let sent: { role?: string } = {};
    server.use(
      http.patch("*/organizations/my/members/:id/role", async ({ request }) => {
        sent = (await request.json()) as { role?: string };
        return HttpResponse.json({
          message: "ok",
          user_id: "member-1",
          role: sent.role,
        });
      }),
    );
    signInWith(["admin:access"]);
    renderSettings();

    const select = await screen.findByRole("combobox", {
      name: /Warehouse Clerk/,
    });
    await userEvent.selectOptions(select, "manager");

    await waitFor(() => expect(sent.role).toBe("manager"));
  });

  it("offers no role control to somebody who is not an administrator", async () => {
    signInWith([]);
    renderSettings();

    await screen.findByText("Warehouse Clerk");
    expect(screen.queryByLabelText(/Warehouse Clerk/)).toBeNull();
  });

  it("spells out what each member may do next to their name", async () => {
    // The role label alone ("Manager") says nothing about the powers, so the
    // row carries the access summary too — one per built-in role.
    server.use(
      http.get("*/organizations/my/members", () =>
        HttpResponse.json({
          items: [
            {
              id: "m-admin",
              email: "ada@example.com",
              full_name: "Ada Admin",
              role: "admin",
            },
            {
              id: "m-manager",
              email: "marek@example.com",
              full_name: "Marek Manager",
              role: "manager",
            },
            {
              id: "m-user",
              email: "ula@example.com",
              full_name: "Ula User",
              role: "user",
            },
            {
              id: "m-viewer",
              email: "ola@example.com",
              full_name: "Ola Viewer",
              role: "viewer",
            },
          ],
          total: 4,
          limit: 20,
          offset: 0,
        }),
      ),
    );
    signInWith([]);
    renderSettings();

    expect(await screen.findByText("Administrator · full access")).toBeTruthy();
    expect(await screen.findByText("Manager · read and write")).toBeTruthy();
    expect(await screen.findByText("Member · read and write")).toBeTruthy();
    expect(await screen.findByText("Viewer · read only")).toBeTruthy();
  });

  it("lets an administrator assign a custom role, sent as role_id", async () => {
    // The dropdown carries both kinds: the four built-in levels and the
    // organization's own roles. A custom role travels as role_id — the enum
    // stays the member's base level.
    const customRole = {
      id: "role-xyz",
      organization_id: "org-1",
      name: "Magazynier",
      permissions: ["items:read", "items:write"],
      is_system: false,
      created_at: null,
    };
    let sent: { role?: string; role_id?: string } = {};
    server.use(
      http.get("*/roles", () => HttpResponse.json(onePage([customRole]))),
      http.patch("*/organizations/my/members/:id/role", async ({ request }) => {
        sent = (await request.json()) as { role?: string; role_id?: string };
        return HttpResponse.json({
          message: "ok",
          user_id: "member-1",
          role: "user",
          role_id: sent.role_id ?? null,
        });
      }),
    );
    signInWith(["admin:access"]);
    renderSettings();

    const select = await screen.findByRole("combobox", {
      name: /Warehouse Clerk/,
    });
    await userEvent.selectOptions(select, "custom:role-xyz");

    await waitFor(() => expect(sent.role_id).toBe("role-xyz"));
    expect(sent.role).toBeUndefined();
  });

  it("names the custom role and its access summary on the row", async () => {
    server.use(
      http.get("*/organizations/my/members", () =>
        HttpResponse.json({
          items: [
            {
              id: "member-9",
              email: "mag@example.com",
              full_name: "Magda Custom",
              role: "user",
              custom_role: {
                id: "role-xyz",
                name: "Magazynier",
                permissions: ["items:read", "items:write"],
              },
            },
          ],
          total: 1,
          limit: 20,
          offset: 0,
        }),
      ),
    );
    signInWith([]);
    renderSettings();

    expect(await screen.findByText("Magazynier · read and write")).toBeTruthy();
  });

  it("says why the member was not removed, in the server's words", async () => {
    // The row's own guard hides the administrator's row, but the server is the
    // one that decides: it refuses to remove the person asking, a member of
    // another organization, and whoever the organization has just lost. A
    // fixed sentence for all three hides the one that happened.
    server.use(
      http.post("*/organizations/my/remove-member/:id", () =>
        HttpResponse.json(
          {
            detail: {
              code: "VALIDATION_ERROR",
              message: "Nie możesz usunąć samego siebie",
            },
          },
          { status: 400 },
        ),
      ),
    );
    signInWith(["admin:access"]);
    renderSettings();

    await userEvent.click(
      await screen.findByRole("button", { name: /^Remove member / }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "Remove" }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Nie możesz usunąć samego siebie",
      ),
    );
  });

  afterEach(() => signOut());
  it("names the person the remove button removes", async () => {
    signInWith(["admin:access"]);
    renderSettings();

    const button = await screen.findByRole("button", {
      name: /^Remove member \S/,
    });
    expect(button).toBeInTheDocument();
  });
});
