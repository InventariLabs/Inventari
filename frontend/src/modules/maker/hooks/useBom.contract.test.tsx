import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { recordRequests } from "@/test/requestLog";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useBomCostEstimate,
  useBomSummary,
  useBomSummaryForTemplates,
  useBomTree,
  useMoveBomLine,
  useTemplateIdsWithBom,
  useWhereUsed,
} from "./useBom";

let client: QueryClient;
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);

beforeEach(() => {
  client = new QueryClient();
});

/**
 * The formula (BoM) screens read one endpoint each. The batched summary must
 * carry every template id the page shows, and a question about a template
 * nobody named must not leave the browser.
 */
describe("formula reads", () => {
  it.each([
    ["useBomTree", () => useBomTree("t1"), "/maker/bom/tree/t1", {}],
    [
      "useBomSummary",
      () => useBomSummary("t1"),
      "/maker/bom/summary",
      { template_ids: "t1" },
    ],
    [
      "useBomSummaryForTemplates",
      () => useBomSummaryForTemplates(["t1", "t2"]),
      "/maker/bom/summary",
      { template_ids: "t1,t2" },
    ],
    [
      "useWhereUsed",
      () => useWhereUsed("t1"),
      "/maker/bom/where-used",
      { template_id: "t1" },
    ],
    [
      "useBomCostEstimate",
      () => useBomCostEstimate("t1", { recipeId: "r1", qty: "4" }),
      "/maker/bom/t1/cost-estimate",
      { recipe_id: "r1", qty: "4" },
    ],
    [
      "useBomCostEstimate without params",
      () => useBomCostEstimate("t1"),
      "/maker/bom/t1/cost-estimate",
      {},
    ],
  ])("%s asks %s", async (_name, hook, path, query) => {
    const log = recordRequests(() => ({}));
    renderHook(hook as () => unknown, { wrapper });
    await waitFor(() => expect(log.length).toBeGreaterThan(0));
    expect(log[0]).toMatchObject({ method: "GET", path, query });
  });

  it("lists the template ids that have a formula, unwrapped from the envelope", async () => {
    recordRequests(() => ({ template_ids: ["t1", "t9"] }));
    const { result } = renderHook(() => useTemplateIdsWithBom(), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(["t1", "t9"]));
  });

  it("does not ask when the caller turned the question off", async () => {
    const log = recordRequests();
    const { result } = renderHook(() => useTemplateIdsWithBom(false), {
      wrapper,
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });

  it.each([
    ["useBomTree", () => useBomTree(undefined)],
    ["useBomSummary", () => useBomSummary(undefined)],
    ["useBomSummaryForTemplates", () => useBomSummaryForTemplates([])],
    ["useWhereUsed", () => useWhereUsed(undefined)],
    ["useBomCostEstimate", () => useBomCostEstimate(undefined)],
  ])("%s stays quiet without a template", async (_name, hook) => {
    const log = recordRequests();
    const { result } = renderHook(hook as () => { fetchStatus: string }, {
      wrapper,
    });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(log).toHaveLength(0);
  });
});

describe("the product list's formula badges", () => {
  it("send one summary request per page, not one per row", async () => {
    const log = recordRequests(() => ({
      items: [{ template_id: "t1", line_count: 2, default_recipe_id: "r1" }],
    }));
    const ids = ["t1", "t2", "t3"];
    // The test setup drops unused queries at once; the app keeps them for
    // minutes, which is what lets a seeded answer wait for its cell.
    client.setDefaultOptions({ queries: { gcTime: 5 * 60_000 } });
    // The formula column mounts its cells once the page's answer is in, so
    // the cells here wait for it too.
    const { result } = renderHook(
      () => {
        const batch = useBomSummaryForTemplates(ids);
        const cells = ids.map((id) =>
          useBomSummary(batch.data ? id : undefined),
        );
        return { batch, cells };
      },
      { wrapper },
    );
    await waitFor(() => expect(result.current.batch.data).toBeDefined());
    await new Promise((r) => setTimeout(r, 20));

    expect(log).toHaveLength(1);
    expect(log[0].query).toEqual({ template_ids: "t1,t2,t3" });
    expect(result.current.cells[0].data?.items).toHaveLength(1);
    expect(result.current.cells[1].data?.items).toEqual([]);
  });
});

describe("useMoveBomLine", () => {
  it("posts the move to the line and refreshes that template's tree", async () => {
    const log = recordRequests(() => ({ id: "l1" }));
    client.setQueryDefaults(queryKeys.maker.bomTree("t1"), {
      gcTime: Infinity,
    });
    client.setQueryData(queryKeys.maker.bomTree("t1"), {});
    const { result } = renderHook(() => useMoveBomLine("t1"), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        lineId: "l1",
        data: { new_parent_id: "p2" } as never,
      }),
    );
    expect(log[0]).toMatchObject({
      method: "POST",
      path: "/maker/bom/l1/move",
      body: { new_parent_id: "p2" },
    });
    expect(
      client.getQueryState(queryKeys.maker.bomTree("t1"))?.isInvalidated,
    ).toBe(true);
  });
});
