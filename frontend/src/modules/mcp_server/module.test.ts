import { describe, expect, it } from "vitest";

import { moduleRegistry } from "@/module-sdk";

import "./module";

describe("MCP Server module registration", () => {
  it("registers the launcher tile and the settings-reachable page", () => {
    const module = moduleRegistry.getModule("mcp_server");

    expect(module?.launcher?.displayName).toBe("mcp_server:navigation.title");
    expect(module?.routes?.map((route) => route.path)).toEqual(["/mcp-server"]);
  });
});
