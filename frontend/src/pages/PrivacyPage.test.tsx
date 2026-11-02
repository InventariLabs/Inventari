import { render, screen, within } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { ModulesProvider } from "@/contexts/ModulesContext";
import type { InitStatus } from "@/lib/api/auth";
import App from "@/App";
import PrivacyPage from "./PrivacyPage";

/**
 * The privacy page: public, the same text on every install, and the one part
 * that differs — who runs it — read from the server's configuration.
 */
describe("PrivacyPage", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  const serveStatus = (status: Partial<InitStatus>) =>
    server.use(
      http.get("/api/v1/auth/init-status", () =>
        HttpResponse.json({ is_initialized: true, ...status }),
      ),
    );

  const renderPage = () =>
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/privacy"]}>
          <PrivacyPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

  it("names the operator and links an email contact as a message", async () => {
    serveStatus({
      operator_name: "Example Foods Ltd",
      operator_contact: "privacy@example.com",
    });

    renderPage();

    expect(
      await screen.findByText("It is run by Example Foods Ltd."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "privacy@example.com" }),
    ).toHaveAttribute("href", "mailto:privacy@example.com");
    // Configured, so the administrator's hint has nothing left to ask for.
    expect(screen.queryByText(/OPERATOR_NAME/)).not.toBeInTheDocument();
  });

  it("says plainly that an unconfigured install names nobody", async () => {
    serveStatus({ operator_name: null, operator_contact: null });

    renderPage();

    expect(
      await screen.findByText("Its operator has not published their name."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No contact has been published/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Set OPERATOR_NAME and OPERATOR_CONTACT/),
    ).toBeInTheDocument();
  });

  it("opens a web-address contact and never puts another scheme in a link", async () => {
    serveStatus({
      operator_name: "Example",
      operator_contact: "https://example.com/contact",
    });
    const { unmount } = renderPage();

    expect(
      await screen.findByRole("link", { name: "https://example.com/contact" }),
    ).toHaveAttribute("href", "https://example.com/contact");
    unmount();

    queryClient.clear();
    serveStatus({
      operator_name: "Example",
      operator_contact: "javascript:alert(1)",
    });
    renderPage();

    expect(await screen.findByText("javascript:alert(1)")).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "javascript:alert(1)" }),
    ).not.toBeInTheDocument();
  });

  it("tells an ordinary install's visitor how to ask for a copy or deletion", async () => {
    serveStatus({ is_demo: false });

    renderPage();

    expect(
      await screen.findByText(/for a copy of the data held about you/),
    ).toBeInTheDocument();
    // Deletion rewrites the account, not what was written about it before:
    // the page says so rather than promising an anonymous history.
    expect(
      screen.getByText(/can remain in records written before the deletion/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/anonymous account/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "This is a public demo" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/a second cookie/)).not.toBeInTheDocument();
  });

  it("tells a demo visitor what the nightly wipe deletes and how long the server's logs are kept", async () => {
    serveStatus({ is_demo: true });

    renderPage();

    const demo = (
      await screen.findByRole("heading", { name: "This is a public demo" })
    ).closest("section");
    expect(demo).not.toBeNull();
    expect(
      within(demo as HTMLElement).getByText(/Every night the whole demo/),
    ).toBeInTheDocument();
    expect(
      within(demo as HTMLElement).getByText(/one inbox that every visitor/),
    ).toBeInTheDocument();
    expect(screen.getByText(/a second cookie/)).toBeInTheDocument();
    expect(
      screen.getByText(
        /technical logs are not part of that wipe; they are kept for seven days/,
      ),
    ).toBeInTheDocument();
    // The way to the operator stays open for ordinary requests.
    expect(
      screen.getByText(/for a copy of the data held about you/),
    ).toBeInTheDocument();
  });

  it("does not claim an operator is unset when the server could not be asked", async () => {
    server.use(
      http.get(
        "/api/v1/auth/init-status",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    renderPage();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(
      screen.queryByText("Its operator has not published their name."),
    ).not.toBeInTheDocument();
  });

  it("is a route of the application that renders without a session", async () => {
    serveStatus({ operator_name: "Example Foods Ltd" });

    render(
      <QueryClientProvider client={queryClient}>
        <ModulesProvider>
          <App initialEntries={["/privacy"]} />
        </ModulesProvider>
      </QueryClientProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "Privacy", level: 2 }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("It is run by Example Foods Ltd."),
    ).toBeInTheDocument();
    // Still here, not sent on to the sign-in form.
    expect(
      screen.queryByRole("button", { name: /Sign in/i }),
    ).not.toBeInTheDocument();
  });
});
