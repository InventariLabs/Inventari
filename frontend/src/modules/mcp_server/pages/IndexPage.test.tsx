import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { PageHeaderContext } from "@/hooks/useModulePageHeader";

import IndexPage from "./IndexPage";

describe("MCP Server page", () => {
  it("names the module and links to its settings", () => {
    render(
      <PageHeaderContext.Provider value={{ data: {}, setHeader: vi.fn() }}>
        <MemoryRouter>
          <IndexPage />
        </MemoryRouter>
      </PageHeaderContext.Provider>,
    );

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
});
