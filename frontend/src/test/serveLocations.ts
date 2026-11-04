import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { makeStorageSummary } from "@/test/factories/storage";
import type { StorageLocationNode, StorageLocationSummary } from "@/types";
import { LOCATION_PATH_SEPARATOR } from "@/utils/helpers";

/**
 * Serve `GET /locations` and `GET /locations/tree` the way the backend does:
 * a page of the rows that match `q`, `ids`, `parent_id` and `top_level`, with
 * the real envelope, and the tree one level at a time when `depth` or
 * `parent_id` asks. A screen that reads the catalogue whole shows up as a
 * request the test can count.
 *
 * Archived and virtual rows are told apart the way the endpoint tells them:
 * `usage` other than `internal` and `settings.archived` stay out unless asked.
 *
 * Returns the query strings it saw, in order.
 */
export function serveLocations(
  rows: Array<Partial<StorageLocationSummary> & { id: string; name: string }>,
): URLSearchParams[] {
  const requests: URLSearchParams[] = [];
  const all = rows.map((row) => makeStorageSummary(row));
  const byId = new Map(all.map((row) => [row.id, row]));
  const pathOf = (row: StorageLocationSummary): string => {
    const parts: string[] = [];
    let current: StorageLocationSummary | undefined = row;
    const seen = new Set<string>();
    while (current && !seen.has(current.id)) {
      seen.add(current.id);
      parts.unshift(current.name);
      current = current.parent_id ? byId.get(current.parent_id) : undefined;
    }
    return parts.join(LOCATION_PATH_SEPARATOR);
  };
  const archived = (row: StorageLocationSummary) =>
    (row.settings as { archived?: boolean } | null)?.archived === true;

  server.use(
    http.get("/api/v1/locations", ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const usage = params.get("usage") ?? "internal";
      const ids = params.getAll("ids");
      const needle = (params.get("q") ?? "").toLowerCase();
      const hits = all
        .filter((row) => usage === "all" || row.usage === usage)
        .filter(
          (row) => params.get("include_archived") === "true" || !archived(row),
        )
        .filter(
          (row) =>
            params.get("exclude_module_contexts") !== "true" ||
            !row.context_tag,
        )
        .filter((row) => ids.length === 0 || ids.includes(row.id))
        .filter(
          (row) =>
            !params.get("parent_id") ||
            row.parent_id === params.get("parent_id"),
        )
        .filter((row) => params.get("top_level") !== "true" || !row.parent_id)
        .filter((row) => {
          const under = params.get("under");
          if (!under) return true;
          // Strictly below: the place itself is not inside itself.
          let current = row.parent_id ? byId.get(row.parent_id) : undefined;
          const seen = new Set<string>();
          while (current && !seen.has(current.id)) {
            if (current.id === under) return true;
            seen.add(current.id);
            current = current.parent_id
              ? byId.get(current.parent_id)
              : undefined;
          }
          return false;
        })
        .filter((row) => !needle || pathOf(row).toLowerCase().includes(needle))
        .map((row) => ({ ...row, full_path: pathOf(row) }));
      const limit = Number(params.get("limit") ?? 50);
      const offset = Number(params.get("offset") ?? 0);
      return HttpResponse.json({
        items: hits.slice(offset, offset + limit),
        total: hits.length,
        limit,
        offset,
        has_more: offset + limit < hits.length,
      });
    }),
    http.get("/api/v1/locations/tree", ({ request }) => {
      const params = new URL(request.url).searchParams;
      requests.push(params);
      const parent = params.get("parent_id");
      const depth = params.get("depth")
        ? Number(params.get("depth"))
        : parent
          ? 1
          : Infinity;
      const live = all.filter(
        (row) =>
          row.usage === (params.get("usage") ?? "internal") ||
          params.get("usage") === "all",
      );
      const node = (
        row: StorageLocationSummary,
        left: number,
      ): StorageLocationNode => {
        const children = live.filter((c) => c.parent_id === row.id);
        return {
          id: row.id,
          name: row.name,
          parent_id: row.parent_id ?? null,
          usage: row.usage,
          location_type_id: null,
          short_code: row.short_code ?? null,
          context_tag: row.context_tag ?? null,
          items_count: row.items_count,
          subtree_items_count: row.subtree_items_count,
          children_count: children.length,
          children: left > 1 ? children.map((c) => node(c, left - 1)) : [],
        };
      };
      const start = parent
        ? live.filter((row) => row.parent_id === parent)
        : live.filter((row) => !row.parent_id || !byId.has(row.parent_id));
      return HttpResponse.json(start.map((row) => node(row, depth)));
    }),
  );
  return requests;
}
