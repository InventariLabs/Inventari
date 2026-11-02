import { expect, type Page, type Response } from "@playwright/test";

interface WaitOptions {
  method?: string;
  timeout?: number;
}

/**
 * Arms a wait for the request a page makes to fetch its own data, and asserts
 * the server actually answered it.
 *
 * A visible `h1` only proves the shell mounted. Page headers come from
 * `useModulePageHeader`, so they render whether the query succeeded, failed or
 * was never sent — a purchase-orders templates test stayed green for days
 * while the endpoint answered 404 and the page showed a fake empty state.
 *
 * Call this *before* the navigation or click that triggers the request:
 *
 *   const loaded = expectApiOk(page, "/api/v1/items/archived");
 *   await page.goto("/inventory/items/archived");
 *   await loaded;
 */
export function expectApiOk(
  page: Page,
  url: string | RegExp,
  { method = "GET", timeout = 15000 }: WaitOptions = {},
): Promise<Response> {
  const matches = (candidate: string) =>
    typeof url === "string" ? candidate.includes(url) : url.test(candidate);

  return page
    .waitForResponse(
      (response) =>
        response.request().method() === method && matches(response.url()),
      { timeout },
    )
    .catch(() => {
      // A wrong URL segment produces no matching response at all rather than
      // a failing one, so say that out loud — the bare Playwright timeout
      // reads like a slow page.
      throw new Error(
        `No ${method} response matching ${url} within ${timeout}ms. ` +
          `The page either never requested it (wrong URL?) or the request never finished.`,
      );
    })
    .then((response) => {
      expect(
        response.ok(),
        `${method} ${response.url()} answered ${response.status()}`,
      ).toBeTruthy();
      return response;
    });
}
