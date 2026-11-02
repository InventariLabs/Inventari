import { type PlaywrightWorkerArgs } from "@playwright/test";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "../fixtures/credentials";
import { ApiHelper } from "./api";

/**
 * Sets whether receiving, picking and put-away sessions ask for the shelf's
 * label before they move on, and returns what it was. The rule belongs to the
 * whole organisation, so a spec that needs it in one state runs in the
 * one-worker project and puts it back when it is done.
 */
export async function setShelfScanRule(
  playwright: PlaywrightWorkerArgs["playwright"],
  baseURL: string | undefined,
  on: boolean,
): Promise<boolean> {
  const ctx = await playwright.request.newContext({ baseURL });
  try {
    const token = (await new ApiHelper(ctx).login(ADMIN_EMAIL, ADMIN_PASSWORD))
      .access_token;
    const headers = { Authorization: `Bearer ${token}` };
    const read = await ctx.get("/api/v1/warehouse/profile", { headers });
    const was = (await read.json()).confirm_shelf_by_scan === true;
    const put = await ctx.put("/api/v1/warehouse/profile", {
      headers,
      data: { confirm_shelf_by_scan: on },
    });
    if (!put.ok()) {
      throw new Error(`Could not set the shelf scan: ${await put.text()}`);
    }
    return was;
  } finally {
    await ctx.dispose();
  }
}
