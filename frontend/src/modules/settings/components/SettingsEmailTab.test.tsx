import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import SettingsEmailTab from "./SettingsEmailTab";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() },
}));

const baseOrg = {
  id: "org-1",
  name: "Test Org",
  currency: "PLN",
  created_at: "2026-01-01T00:00:00Z",
  created_by: null,
  enabled_modules: ["core", "items"],
};

function mockSmtp(smtp: Record<string, unknown>) {
  server.use(
    http.get("*/organizations/my", () =>
      HttpResponse.json({ ...baseOrg, settings: { smtp } }),
    ),
  );
}

async function renderExpanded() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const utils = render(
    <QueryClientProvider client={queryClient}>
      <SettingsEmailTab />
    </QueryClientProvider>,
  );
  await userEvent.click(await screen.findByText("Email Server (SMTP)"));
  return utils;
}

describe("SettingsEmailTab", () => {
  it("reads the encryption of a configuration saved before the field existed", async () => {
    // 465 used to mean plain SMTP with no STARTTLS — login and message in the
    // clear. The stored port now resolves to the transport it implies, and the
    // screen says which one that is.
    mockSmtp({ host: "smtp.example.com", port: 465, user: "u", password: "p" });
    await renderExpanded();

    await waitFor(() =>
      expect(
        screen.getByText("SSL/TLS (usually port 465)"),
      ).toBeInTheDocument(),
    );
  });

  it("warns when the administrator chooses no encryption at all", async () => {
    mockSmtp({
      host: "smtp.example.com",
      port: 25,
      user: "u",
      password: "p",
      encryption: "none",
    });
    await renderExpanded();

    await waitFor(() =>
      expect(
        screen.getByText(
          "Without encryption the username, password and message travel in plain text.",
        ),
      ).toBeInTheDocument(),
    );
  });

  it("keeps the test button's label while the test is running", async () => {
    mockSmtp({ host: "smtp.example.com", port: 587, user: "u", password: "p" });
    server.use(
      http.post(
        "*/organizations/my/test-email",
        () => new Promise(() => undefined),
      ),
    );
    await renderExpanded();

    const testButton = await screen.findByRole("button", {
      name: /Send Test Email/,
    });
    await userEvent.click(testButton);

    // The connection can take as long as the SMTP timeout allows; a button
    // that becomes a bare spinner stops saying what is being waited on.
    await waitFor(() =>
      expect(testButton.querySelector(".animate-spin")).toBeInTheDocument(),
    );
    expect(testButton).toBeDisabled();
    expect(screen.getByText("Send Test Email")).toBeInTheDocument();
  });
});

describe("SettingsEmailTab — the login", () => {
  it("names the missing password instead of saving half a login", async () => {
    mockSmtp({
      host: "relay.internal",
      port: 25,
      user: "mailer",
      password: "",
    });
    const saved = vi.fn();
    server.use(
      http.put("*/organizations/my", () => {
        saved();
        return HttpResponse.json(baseOrg);
      }),
    );
    await renderExpanded();

    await userEvent.click(
      await screen.findByRole("button", { name: /Save Email Settings/ }),
    );

    expect(
      await screen.findByText(/Enter the password for this username/),
    ).toBeInTheDocument();
    expect(saved).not.toHaveBeenCalled();
  });

  it("lets a relay that asks for no login be tested", async () => {
    mockSmtp({ host: "relay.internal", port: 25, encryption: "none" });
    const tested = vi.fn();
    server.use(
      http.post("*/organizations/my/test-email", () => {
        tested();
        return HttpResponse.json({ message: "ok" });
      }),
    );
    await renderExpanded();

    await userEvent.click(
      await screen.findByRole("button", { name: /Send Test Email/ }),
    );

    await waitFor(() => expect(tested).toHaveBeenCalled());
  });
});

describe("SettingsEmailTab — the state, before anything is expanded", () => {
  function renderCollapsed(canSend: boolean) {
    server.use(
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...baseOrg, can_send_email: canSend }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    return render(
      <QueryClientProvider client={queryClient}>
        <SettingsEmailTab />
      </QueryClientProvider>,
    );
  }

  it("says the installation cannot send mail without being opened", async () => {
    renderCollapsed(false);

    expect(await screen.findByText("Not configured")).toBeInTheDocument();
  });

  it("says it can, when the server can send", async () => {
    // Read from the server, not from the organization's own SMTP block: an
    // installation-wide mail server sends for organizations that have none.
    renderCollapsed(true);

    expect(await screen.findByText("Sends mail")).toBeInTheDocument();
  });
});

describe("SettingsEmailTab — on the public demo", () => {
  function renderDemo(initStatus: Record<string, unknown>) {
    server.use(
      http.get("*/auth/init-status", () => HttpResponse.json(initStatus)),
      http.get("*/organizations/my", () =>
        HttpResponse.json({ ...baseOrg, can_send_email: true }),
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    return render(
      <QueryClientProvider client={queryClient}>
        <SettingsEmailTab />
      </QueryClientProvider>,
    );
  }

  it("says where mail is captured instead of offering the form", async () => {
    // A demo publishes its administrator login, so the form would let any
    // visitor aim the demo server at a host they choose. The backend refuses
    // the save and ignores stored settings; the screen says what happens
    // instead and where to read what the app would have sent.
    renderDemo({
      is_initialized: true,
      is_demo: true,
      demo_inbox_url: "https://demo.example/mailpit/",
    });

    expect(
      await screen.findByText(/the app sends no real email/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open the demo inbox/i }),
    ).toHaveAttribute("href", "https://demo.example/mailpit/");
    // No accordion and no form: nothing here can be typed at, because nothing
    // here would take effect.
    expect(
      screen.queryByRole("button", { name: /Email Server/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText("SMTP Host")).not.toBeInTheDocument();
  });

  it("says mail is captured even when the inbox URL is missing", async () => {
    // The marker and the URL are separate keys: a demo that forgot the URL
    // still refuses the settings, and the screen must not pretend otherwise
    // or render a dead link.
    renderDemo({ is_initialized: true, is_demo: true });

    expect(
      await screen.findByText(/the app sends no real email/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /open the demo inbox/i }),
    ).not.toBeInTheDocument();
  });
});
