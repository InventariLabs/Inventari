import type { Page, Response } from "@playwright/test";
import { expect } from "@playwright/test";

/** What every paged list endpoint answers with. */
export interface ListBody {
  items: unknown[];
  total: number;
}

/**
 * Arms a wait for the list request a search sends and resolves to its
 * response. The match is the method, the path and the exact search string —
 * and nothing else may stand in for it: a page that sends a second query with
 * the same search (the recipes page also asks for its favourites tab) would
 * otherwise resolve on whichever answers first, and the assertions would read
 * a query the user is not looking at. `ignoreParams` names the parameters
 * whose presence marks such a sibling query.
 *
 * Call it before the search is typed, await the result after.
 */
export function waitForListResponse(
  page: Page,
  options: { path: string; search: string; ignoreParams?: string[] },
): Promise<Response> {
  const { path, search, ignoreParams = [] } = options;
  return page.waitForResponse(
    (response) => {
      const url = new URL(response.url());
      return (
        response.request().method() === "GET" &&
        url.pathname === path &&
        url.searchParams.get("search") === search &&
        !ignoreParams.some((name) => url.searchParams.has(name))
      );
    },
    { timeout: 10000 },
  );
}

/** The list query's answer to a search that must match nothing. */
export async function expectEmptyListAnswer(response: Response): Promise<void> {
  expect(response.status()).toBe(200);
  const body = (await response.json()) as ListBody;
  expect(body.total).toBe(0);
  expect(body.items).toHaveLength(0);
}
