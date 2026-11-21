import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { PageHeaderContext } from "@/hooks/useModulePageHeader";
import { signInWith, signOut } from "@/test/auth";

import IndexPage from "./IndexPage";

function renderPage() {
  return render(
    <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
      <MemoryRouter>
        <IndexPage />
      </MemoryRouter>
    </PageHeaderContext.Provider>,
  );
}

afterEach(() => {
  signOut();
});

describe("MCP Server page", () => {
  it("names the module and links to its settings", () => {
    // A key is made on a settings screen; this account may open it.
    signInWith(["org:settings:write"]);
    renderPage();

    expect(
      screen.getByText(/Connect an AI agent to this workspace/),
    ).toBeInTheDocument();
    // The page has to say where to connect, not only that the module exists.
    // A client is configured with a whole address; a bare path cannot be
    // pasted into the command the reader runs.
    const endpoint = `${window.location.origin}/api/v1/mcp-server/mcp`;
    expect(screen.getByText(endpoint)).toBeInTheDocument();
    expect(endpoint.startsWith("http")).toBe(true);
    expect(
      screen.getByText(/Send the key in the X-API-Key header/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "MCP Server settings" }),
    ).toHaveAttribute("href", "/settings/modules/mcp_server");
    expect(screen.getByRole("link", { name: "API Keys" })).toHaveAttribute(
      "href",
      "/settings/api-keys",
    );
  });

  it("says which protocol revision a client is answered with", () => {
    // The endpoint serves the 2026-07-28 revision per request, while a client
    // that opens with the initialize handshake negotiates 2025-11-25; the
    // page names both so a client's answer is not a surprise.
    signInWith(["org:settings:write"]);
    renderPage();

    expect(screen.getByText(/2026-07-28/)).toBeInTheDocument();
    expect(screen.getByText(/2025-11-25/)).toBeInTheDocument();
  });

  it("sends a role without settings access to an administrator, not a refusal", () => {
    // A viewer reads this module but cannot open API Keys, where a key is
    // made; the page names that instead of offering a link to a refusal.
    signInWith([]);
    renderPage();

    expect(
      screen.queryByRole("link", { name: "API Keys" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Ask an administrator/)).toBeInTheDocument();
    // The link the account can open stays.
    expect(
      screen.getByRole("link", { name: "MCP Server settings" }),
    ).toHaveAttribute("href", "/settings/modules/mcp_server");
  });
});
