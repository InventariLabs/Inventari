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
    expect(screen.getByText("/api/v1/mcp-server/mcp")).toBeInTheDocument();
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
