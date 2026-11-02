import { describe, it, expect, vi, type Mock } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import { invalidation } from "./invalidation";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * What a document write changes, and what the screens behind it read.
 *
 * `invalidation.documents()` was the funnel for every document mutation —
 * receipts, issues, transfers, corrections, returns — and it invalidated
 * documents and the movement ledger and nothing else. A receipt writes
 * items, quants, lots and the statistics too; with a global five-minute
 * staleTime and no refetch on focus, opening the product list within five
 * minutes of a receipt showed the stock from before it. The stock screens
 * had each patched themselves with a 30-second staleTime — the same bug,
 * found and treated locally three times instead of once here.
 */
const makeClient = () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  vi.spyOn(client, "invalidateQueries");
  return client;
};

const invalidatedKeys = (qc: QueryClient) =>
  (qc.invalidateQueries as unknown as Mock).mock.calls.map(
    (c) => (c[0] as { queryKey: unknown }).queryKey,
  );

describe("invalidation.documents() — what a document write touches", () => {
  it("invalidates the stock a document moved, not only the document", () => {
    const qc = makeClient();

    invalidation.documents(qc);

    const keys = invalidatedKeys(qc);
    expect(keys).toContainEqual(queryKeys.documents.all);
    expect(keys).toContainEqual(queryKeys.items.all);
    expect(keys).toContainEqual(queryKeys.items.allStorageItems);
    expect(keys).toContainEqual(queryKeys.stats.overview);
    expect(keys.map((k) => (k as string[])[0])).toContain("stock-quants");
    expect(keys.map((k) => (k as string[])[0])).toContain("stock-lots");
  });

  it("still narrows to one document when it knows which", () => {
    const qc = makeClient();

    invalidation.documents(qc, "doc-1");

    expect(invalidatedKeys(qc)).toContainEqual(
      queryKeys.documents.detail("doc-1"),
    );
  });
});

describe("the item detail pair — the namespace prefix must reach it", () => {
  // A detail key with a root of its own escapes every prefix invalidation
  // aimed at the namespace: receipts, corrections and returns all funnel
  // through documents() → items(), and an open item card kept the state from
  // before the write for the full five-minute staleTime — with no refetch on
  // focus, for as long as the session lasted.
  it("documents() reaches the detail an open item card reads", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(queryKeys.items.detail("it-1"), { quantity: 5 });

    invalidation.documents(qc);

    expect(
      qc.getQueryState(queryKeys.items.detail("it-1"))?.isInvalidated,
    ).toBe(true);
  });

  it("builds the detail key under the root its namespace invalidates", () => {
    const root = queryKeys.items.all;
    expect(queryKeys.items.detail("it-1").slice(0, root.length)).toEqual(root);
  });
});

// ── The class the two keys above were instances of ─────────────────────────

type Probe = readonly unknown[];

/** A call's worth of a key builder, or the array itself. */
function asKey(value: unknown, arg: unknown): Probe | null {
  if (Array.isArray(value)) return value;
  if (typeof value === "function") {
    const produced = (value as (a: unknown) => unknown)(arg);
    return Array.isArray(produced) ? produced : null;
  }
  return null;
}

/** The stable part of a space's `all` key: `["stock-takes"]` out of
 * `["stock-takes", status]`, the whole array when it takes no parameter. */
function spaceRoot(all: unknown): Probe | null {
  if (Array.isArray(all)) return all;
  const empty = asKey(all, undefined);
  const probed = asKey(all, "probe");
  if (!empty || !probed) return null;
  const shared: unknown[] = [];
  for (let i = 0; i < Math.min(empty.length, probed.length); i += 1) {
    if (empty[i] !== probed[i]) break;
    shared.push(empty[i]);
  }
  return shared;
}

/** Spaces whose `detail` key does not start with their namespace root.
 *
 * The instance fixed above was one key; this is the class. An open detail
 * card is refreshed by the prefix invalidation that clears its namespace,
 * and a detail key whose first segment is singular (or otherwise foreign)
 * escapes every one of them: the writer cannot know the id, the prefix
 * misses, and the card keeps the state from before the write for the whole
 * staleTime — with no refetch on focus, for as long as the session lasts.
 */
export function detailKeyFailures(
  registry: unknown,
  path: string[] = [],
): string[] {
  if (registry === null || typeof registry !== "object") return [];
  const node = registry as Record<string, unknown>;
  const failures: string[] = [];
  const root = spaceRoot(node.all);
  const detail = asKey(node.detail, "probe");
  if (root && detail && !root.every((segment, i) => detail[i] === segment)) {
    failures.push([...path, "detail"].join("."));
  }
  for (const [name, value] of Object.entries(node)) {
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      failures.push(...detailKeyFailures(value, [...path, name]));
    }
  }
  return failures;
}

/** Spaces whose detail deliberately lives elsewhere. Nothing needed one
 * when this check landed; an entry belongs here only when the detail of
 * that space means something other than its list, with the reason written
 * beside it — the check trips on the entry loudly once the reason stops
 * being true. */
const DELIBERATE_DETAIL_ROOTS: ReadonlyArray<{ key: string; reason: string }> =
  [];

describe("every detail key sits under the root its namespace invalidates", () => {
  it("catches a detail key planted under a foreign root", () => {
    const planted = {
      things: { all: ["things"], detail: () => ["thing", "t-1"] },
    };
    expect(detailKeyFailures(planted)).toEqual(["things.detail"]);
  });

  it("finds nothing unexcused in the registry", () => {
    const excused = new Set(DELIBERATE_DETAIL_ROOTS.map((e) => e.key));
    const failures = detailKeyFailures(queryKeys).filter(
      (key) => !excused.has(key),
    );
    expect(failures).toEqual([]);
  });

  it("keeps no exception that stopped being one", () => {
    const failing = new Set(detailKeyFailures(queryKeys));
    const stale = DELIBERATE_DETAIL_ROOTS.filter((e) => !failing.has(e.key));
    expect(stale).toEqual([]);
  });
});

describe("the storages and stockTakes pairs — the prefix must reach them", () => {
  it("storages() reaches the card an open storage page reads", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(queryKeys.storages.detail("s-1"), { name: "Shelf A" });

    invalidation.storages(qc);

    expect(
      qc.getQueryState(queryKeys.storages.detail("s-1"))?.isInvalidated,
    ).toBe(true);
  });

  it("stockTakes() without an id still reaches the take on screen", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    qc.setQueryData(queryKeys.stockTakes.detail("st-1"), { status: "DRAFT" });

    invalidation.stockTakes(qc);

    expect(
      qc.getQueryState(queryKeys.stockTakes.detail("st-1"))?.isInvalidated,
    ).toBe(true);
  });
});
