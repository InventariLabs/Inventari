import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  bomApi,
  type BoMSummaryResponse,
  type WhereUsedResponse,
} from "@/modules/maker/api/bom";
import { queryKeys } from "@/hooks/queries/keys";
import { invalidation } from "@/lib/api/invalidation";
import type {
  BomMoveRequest,
  BomTreeResponse,
  CostBreakdownResponse,
} from "@/modules/maker/types/maker";

export function useBomTree(templateId: string | undefined, recipeId?: string) {
  return useQuery<BomTreeResponse>({
    queryKey: queryKeys.maker.bomTree(templateId ?? "", recipeId),
    queryFn: () => bomApi.getTree(templateId as string, recipeId),
    enabled: !!templateId,
    staleTime: 0,
  });
}

/**
 * BoM existence + line count for a single template.
 * Disabled when templateId is undefined. Used by the product-list
 * 'has BoM' badge, which finds the page's batched answer already in this
 * cache (see `useBomSummaryForTemplates`) and asks on its own only when it
 * stands outside such a page.
 */
export function useBomSummary(templateId: string | undefined) {
  return useQuery<BoMSummaryResponse>({
    queryKey: queryKeys.maker.bomSummary(templateId ?? ""),
    queryFn: () => bomApi.summaryForTemplates([templateId as string]),
    enabled: !!templateId,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

/**
 * BoM existence for a whole page of templates, in one request.
 *
 * The items table asks this to decide whether the formula column is worth a
 * column at all: every product has a template, so the presence of a template
 * says nothing about whether any of them has a formula.
 */
export function useBomSummaryForTemplates(templateIds: string[]) {
  const queryClient = useQueryClient();
  return useQuery<BoMSummaryResponse>({
    queryKey: queryKeys.maker.bomSummaryBatch(templateIds),
    queryFn: async () => {
      const summary = await bomApi.summaryForTemplates(templateIds);
      // The cells of that page read their own template through
      // `useBomSummary`; handing each its slice here is what keeps them from
      // asking again, one request per row. A template the answer leaves out
      // has no formula, and that is an answer worth caching too.
      for (const id of templateIds) {
        queryClient.setQueryData<BoMSummaryResponse>(
          queryKeys.maker.bomSummary(id),
          { items: summary.items.filter((i) => i.template_id === id) },
        );
      }
      return summary;
    },
    enabled: templateIds.length > 0,
    staleTime: 60_000,
  });
}

/**
 * Every template id in the organization that has a formula, in one request.
 *
 * Shares the cache entry with the items table's formula column (same
 * query key), so a search dropdown that marks formulas and a table column
 * that marks them cost one fetch between them. *enabled* is off for the
 * searches that do not mark anything — the query is only worth its round
 * trip to whoever reads it.
 */
export function useTemplateIdsWithBom(enabled = true) {
  return useQuery<string[]>({
    queryKey: queryKeys.maker.bomTemplateIds(),
    queryFn: async () => (await bomApi.templateIdsWithBom()).template_ids,
    enabled,
    staleTime: 60_000,
  });
}

/** Recipes that consume this template as an ingredient (where-used). */
export function useWhereUsed(templateId: string | undefined) {
  return useQuery<WhereUsedResponse>({
    queryKey: [...queryKeys.maker.bomWhereUsed, templateId],
    queryFn: () => bomApi.whereUsed(templateId as string),
    enabled: !!templateId,
    staleTime: 30_000,
  });
}

interface BomCostEstimateParams {
  /** Ask about this formula, not the template's default. */
  recipeId?: string;
  /** Produce this many units — a batch figure, not a per-unit one. */
  qty?: string;
}

/** Per-ingredient cost estimate, at the layer-average rate. */
export function useBomCostEstimate(
  templateId: string | undefined,
  params?: BomCostEstimateParams,
) {
  const recipeId = params?.recipeId;
  const qty = params?.qty;
  return useQuery<CostBreakdownResponse>({
    queryKey: queryKeys.maker.bomCostEstimate(templateId ?? "", recipeId, qty),
    queryFn: () =>
      bomApi.getCostEstimate(templateId as string, {
        recipeId,
        qty,
      }),
    enabled: !!templateId,
    staleTime: 30_000,
  });
}

export function useMoveBomLine(templateId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ lineId, data }: { lineId: string; data: BomMoveRequest }) =>
      bomApi.moveLine(lineId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.maker.bom(templateId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.maker.bomTree(templateId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.maker.bomParents,
      });
      invalidation.maker(queryClient);
    },
  });
}
