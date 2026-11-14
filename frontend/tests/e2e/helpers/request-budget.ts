import type { Page, Request } from "@playwright/test";

export interface RequestTally {
  /** Every API read the page sent, as `path?query`, in order. */
  reads: string[];
  /** The reads that were sent more than once, with how many times. */
  repeated(): Record<string, number>;
}

/**
 * Counts the API reads a screen sends while it loads.
 *
 * A screen that works can still send 24 requests where the previous build
 * sent none, or ask the same endpoint twice because two readers hold the
 * same answer under two cache keys. Neither fails a visibility assertion;
 * both show only as a count. Start it before the navigation, wait for the
 * page to settle, then assert a ceiling and `repeated()`:
 *
 *   const tally = countApiReads(page);
 *   await page.goto("/launcher");
 *   await page.waitForLoadState("networkidle");
 *   expect(tally.repeated()).toEqual({});
 *   expect(tally.reads.length).toBeLessThanOrEqual(BUDGET);
 */
export function countApiReads(page: Page): RequestTally {
  const reads: string[] = [];
  page.on("request", (request: Request) => {
    if (request.method() !== "GET") return;
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/v1/")) return;
    reads.push(`${url.pathname}${url.search}`);
  });
  return {
    reads,
    repeated() {
      const seen: Record<string, number> = {};
      for (const read of reads) seen[read] = (seen[read] ?? 0) + 1;
      return Object.fromEntries(
        Object.entries(seen).filter(([, count]) => count > 1),
      );
    },
  };
}
