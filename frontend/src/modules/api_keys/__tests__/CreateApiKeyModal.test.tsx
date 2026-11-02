import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test/mocks/server";
import CreateApiKeyModal from "../components/CreateApiKeyModal";

const option = (key: string) => ({
  key,
  label_key: `permissions:system.${key.replace(/:/g, "_")}`,
  description_key: null,
});

const capabilities = (scopes: string[]) => ({
  catalog: [
    option("items:read"),
    option("items:write"),
    option("items:delete"),
    { ...option("printing:agent"), label_key: "printing:permissions.agent" },
  ],
  grantable: ["items:read", "items:write", "items:delete", "printing:agent"],
  default_permissions: ["items:read", "org:read"],
  withheld_permissions: ["org:settings:write"],
  admin_areas_blocked: true,
  header: "X-API-Key",
  scopes: scopes.map((name) => ({ name, permissions: ["printing:agent"] })),
});

function renderModal(onSubmit = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <CreateApiKeyModal
        isLoading={false}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return onSubmit;
}

describe("CreateApiKeyModal", () => {
  it("issues a printing key when asked for one", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities(["printing"])),
      ),
    );
    const onSubmit = renderModal();

    await userEvent.type(screen.getByRole("textbox"), "garage printer");
    await userEvent.selectOptions(
      await screen.findByRole("combobox", { name: /what the key is for/i }),
      "printing",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /generate key/i }),
    );

    expect(onSubmit).toHaveBeenCalledWith(
      "garage printer",
      null,
      ["printing"],
      ["printing:agent"],
    );
  });

  it("issues an ordinary key with the default set the reader may grant", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities(["printing"])),
      ),
    );
    const onSubmit = renderModal();

    await screen.findByRole("combobox", { name: /what the key is for/i });
    await userEvent.type(screen.getByRole("textbox"), "backup script");
    await userEvent.click(
      screen.getByRole("button", { name: /generate key/i }),
    );

    // `org:read` is in the default set but not the reader's to grant, and the
    // default carries no write permission: that is a tick somebody puts there.
    expect(onSubmit).toHaveBeenCalledWith(
      "backup script",
      null,
      [],
      ["items:read"],
    );
    const [, , , permissions] = onSubmit.mock.calls[0] as [
      string,
      null,
      string[],
      string[],
    ];
    expect(permissions.every((p) => p.endsWith(":read"))).toBe(true);
  });

  it("offers no choice where the server knows no scope", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities([])),
      ),
    );
    renderModal();

    await waitFor(() =>
      expect(
        screen.queryByRole("combobox", { name: /what the key is for/i }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getAllByRole("combobox")).toHaveLength(1);
  });

  it("issues the permissions ticked, and only those", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities([])),
      ),
    );
    const onSubmit = renderModal();

    await userEvent.type(screen.getByRole("textbox"), "importer");
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Add products and change stock levels",
      }),
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: "Delete products" }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /generate key/i }),
    );

    expect(onSubmit).toHaveBeenCalledWith(
      "importer",
      null,
      [],
      ["items:delete", "items:read", "items:write"],
    );
  });

  it("offers only what the reader may grant, and names what no key carries", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities([])),
      ),
    );
    renderModal();
    const sheet = await screen.findByRole("dialog");

    expect(
      await within(sheet).findByRole("checkbox", {
        name: "Read products and stock levels",
      }),
    ).toBeChecked();
    expect(
      within(sheet).getByRole("checkbox", {
        name: "Add products and change stock levels",
      }),
    ).not.toBeChecked();
    expect(
      within(sheet).queryByRole("checkbox", { name: /organization/i }),
    ).not.toBeInTheDocument();
    expect(within(sheet).getByText("Never on a key")).toBeInTheDocument();
    expect(
      within(sheet).getByText(/Administer the organization/),
    ).toBeInTheDocument();
  });

  it("issues nothing with every permission unticked", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities([])),
      ),
    );
    renderModal();

    await userEvent.type(screen.getByRole("textbox"), "nothing");
    await userEvent.click(
      await screen.findByRole("checkbox", {
        name: "Read products and stock levels",
      }),
    );

    expect(
      screen.getByRole("button", { name: /generate key/i }),
    ).toBeDisabled();
  });

  it("says inside the sheet what a scoped key gets instead of the ticks", async () => {
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        HttpResponse.json(capabilities(["printing"])),
      ),
    );
    renderModal();
    const sheet = await screen.findByRole("dialog");
    await within(sheet).findByRole("checkbox", {
      name: "Add products and change stock levels",
    });

    await userEvent.selectOptions(
      within(sheet).getByRole("combobox", { name: /what the key is for/i }),
      "printing",
    );

    expect(within(sheet).getByText(/works only for/i)).toBeInTheDocument();
    expect(within(sheet).getByText("Act as a print agent")).toBeInTheDocument();
    expect(within(sheet).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("says the scopes could not be loaded, and loads them on retry", async () => {
    let failing = true;
    server.use(
      http.get("/api/v1/api-keys/capabilities", () =>
        failing
          ? HttpResponse.json({ detail: "boom" }, { status: 500 })
          : HttpResponse.json(capabilities(["printing"])),
      ),
    );
    renderModal();

    expect(
      await screen.findByText(/could not be loaded, so no key can be issued/i),
    ).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), "blind");
    expect(
      screen.getByRole("button", { name: /generate key/i }),
    ).toBeDisabled();
    failing = false;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(
      await screen.findByRole("combobox", { name: /what the key is for/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/could not be loaded, so no key can be issued/i),
    ).not.toBeInTheDocument();
  });
});
