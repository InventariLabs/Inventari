import type { APIRequestContext } from "@playwright/test";
import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

/**
 * MCP Server — the two screens the module offers, through the browser.
 *
 * The page is the only place a person copies the address an MCP client is
 * configured with, so it has to show a whole one. The settings card is the
 * only place an organization names the hosts it answers on, and its list
 * settings are edited one value per line; a save that sends the lines as one
 * string is refused by the API (SETTINGS_VALUE_NOT_ARRAY), which is what the
 * card did before the editor existed.
 */

test.describe.configure({ mode: "serial" });

test.describe("MCP Server — the page and the list editor", () => {
  let api: ApiHelper;
  let ctx: APIRequestContext;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    ctx = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(ctx);
    token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
    // MCP Server requires API Keys; both toggles are idempotent.
    await api.toggleModule(token, "api_keys", true);
    await api.toggleModule(token, "mcp_server", true);
  });

  test.afterAll(async () => {
    await api
      .setModuleSettings(token, "mcp_server", {
        allowed_hosts: [],
        allowed_origins: [],
      })
      .catch(() => {});
    await ctx.dispose();
  });

  test("shows the whole endpoint address a client is configured with", async ({
    page,
    authenticatedPage,
    baseURL,
  }) => {
    await page.goto("/mcp-server");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});

    await expect(
      page.getByRole("heading", { level: 1, name: /mcp server/i }),
    ).toBeVisible({ timeout: 15000 });

    const origin = new URL(baseURL ?? "http://127.0.0.1:5173").origin;
    await expect(
      page.getByText(`${origin}/api/v1/mcp-server/mcp`),
    ).toBeVisible();
  });

  test("saves two allowed hosts and keeps them after a reload", async ({
    page,
    authenticatedPage,
  }) => {
    await page.goto("/settings/modules/mcp_server");
    const list = page.getByTestId("field-allowed_hosts");
    await expect(list).toBeVisible({ timeout: 15000 });

    await list.fill("inventari.example.org\nmcp.example.org");
    await page.getByRole("button", { name: /^save$/i }).click();
    await expect(page.getByText(/settings saved/i)).toBeVisible({
      timeout: 10000,
    });

    await page.reload();
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(page.getByTestId("field-allowed_hosts")).toHaveValue(
      "inventari.example.org\nmcp.example.org",
      { timeout: 15000 },
    );
  });
});
