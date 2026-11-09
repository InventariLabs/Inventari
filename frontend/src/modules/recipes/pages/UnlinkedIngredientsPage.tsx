import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CircleCheck, Link2, Loader2, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { extractApiError, extractApiErrorCode } from "@/lib/errors";
import { unitLabel } from "@/lib/i18nHelpers";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryResult } from "@/components/ui/QueryResult";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { useAiPurposes } from "@/modules/settings/hooks/useAiConnections";
import IngredientLinkButton from "../components/IngredientLinkButton";
import { RECIPES_PURPOSE_KEY } from "../components/RecipesAiSettings";
import {
  useBulkLinkIngredients,
  useSuggestIngredientMatches,
  useUnlinkedIngredients,
} from "../hooks/useIngredientLinking";
import type {
  IngredientMatchProposal,
  UnlinkedIngredient,
} from "../types/linking";
import { fmtQty } from "../utils";

interface Proposal {
  templateId: string;
  templateName: string;
}

function proposalsById(
  proposals: IngredientMatchProposal[],
): Record<string, Proposal> {
  const byId: Record<string, Proposal> = {};
  for (const proposal of proposals) {
    byId[proposal.ingredient_id] = {
      templateId: proposal.template_id,
      templateName: proposal.template_name,
    };
  }
  return byId;
}

/**
 * The global screen that links recipe ingredients to stock products.
 *
 * The recipe detail page links one ingredient at a time, which makes a
 * book imported before the catalogue existed a hundred manual visits. Here
 * every unlinked ingredient is one row: ask the matcher for proposals, tick
 * the ones that are right, and write them in one call. The per-row "link"
 * button stays for rows the model could not answer.
 */
export default function UnlinkedIngredientsPage() {
  const { t } = useTranslation("recipes");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("recipes");
  const unlinkedQuery = useUnlinkedIngredients();
  const { mutate: suggest, isPending: isSuggesting } =
    useSuggestIngredientMatches();
  const bulkLinkMutation = useBulkLinkIngredients();
  const [proposals, setProposals] = useState<Record<string, Proposal>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // The 503 this screen answers for matching names the purpose by its
  // registry label, the same way RecipeImportManager does for imports — the
  // raw key must not reach the reader.
  // Only the label of the 503 above depends on this read; when it fails the
  // fallback label is used and the refusal itself is still shown, so the
  // failure is deliberately not surfaced on its own.
  const { data: purposes } = useAiPurposes();
  const recipesPurpose = purposes?.find((p) => p.key === RECIPES_PURPOSE_KEY);
  const purposeLabel = recipesPurpose
    ? t(recipesPurpose.label_key, { defaultValue: recipesPurpose.key })
    : t("recipes:ai.purposeLabel");

  const runSuggest = useCallback(() => {
    suggest(undefined, {
      onSuccess: (result) => {
        setProposals(proposalsById(result.proposals));
        setSelected(
          new Set(result.proposals.map((proposal) => proposal.ingredient_id)),
        );
        if (result.proposals.length === 0) {
          toast.info(t("linking.suggest_empty"));
        }
      },
      onError: (error) => {
        if (extractApiErrorCode(error) === "LLM_PURPOSE_UNBOUND") {
          toast.error(
            t("linking.suggest_failed_ai_not_configured", {
              purpose: purposeLabel,
            }),
          );
          return;
        }
        toast.error(extractApiError(error, t("linking.suggest_failed")));
      },
    });
  }, [suggest, t, purposeLabel]);

  // Matching proposals for a list that never loaded has nothing to match.
  const listFailed = unlinkedQuery.isError;

  useEffect(() => {
    setHeader({
      title: t("linking.title"),
      subtitle: t("linking.subtitle"),
      actions: canWrite ? (
        <Button
          onClick={runSuggest}
          disabled={isSuggesting || listFailed}
          leftIcon={
            isSuggesting ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <Sparkles size={16} />
            )
          }
        >
          {isSuggesting ? t("linking.suggesting") : t("linking.suggest")}
        </Button>
      ) : undefined,
    });
  }, [t, setHeader, canWrite, isSuggesting, listFailed, runSuggest]);

  const items = unlinkedQuery.data?.items ?? [];
  const proposedItems = items.filter((item) => proposals[item.id]);
  const selectedCount = proposedItems.filter((item) =>
    selected.has(item.id),
  ).length;
  const allSelected =
    proposedItems.length > 0 &&
    proposedItems.every((item) => selected.has(item.id));

  const toggleOne = (id: string) => {
    setSelected((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected(
      allSelected ? new Set() : new Set(proposedItems.map((item) => item.id)),
    );
  };

  const handleApprove = () => {
    const links = proposedItems
      .filter((item) => selected.has(item.id))
      .map((item) => ({
        ingredient_id: item.id,
        template_id: proposals[item.id].templateId,
      }));
    if (links.length === 0) return;
    bulkLinkMutation.mutate(links, {
      onSuccess: (result) => {
        toast.success(t("linking.linked_success", { count: result.linked }));
        setProposals((previous) => {
          const next = { ...previous };
          for (const link of links) delete next[link.ingredient_id];
          return next;
        });
        setSelected(new Set());
      },
      onError: (error) => {
        toast.error(extractApiError(error, t("linking.link_failed")));
      },
    });
  };

  const renderRow = (ingredient: UnlinkedIngredient) => {
    const proposal = proposals[ingredient.id];
    return (
      <tr
        key={ingredient.id}
        className="border-b border-border last:border-b-0"
      >
        <td className="py-2.5 pl-4 pr-2 align-middle w-10">
          <Checkbox
            checked={proposal ? selected.has(ingredient.id) : false}
            disabled={!proposal || !canWrite}
            onChange={() => toggleOne(ingredient.id)}
            aria-label={t("linking.select_row", { name: ingredient.name })}
          />
        </td>
        <td className="py-2.5 pr-4 align-middle">
          <span className="block text-sm font-semibold text-on">
            {ingredient.name}
          </span>
          <span className="block text-xs text-on-muted tabular-nums">
            {fmtQty(Number(ingredient.quantity))}
            {ingredient.uom_symbol
              ? ` ${unitLabel(t, ingredient.uom_symbol)}`
              : ""}
          </span>
        </td>
        <td className="py-2.5 pr-4 align-middle">
          <Link
            to={`/recipes/${ingredient.recipe_id}`}
            className="text-sm text-on-primary hover:underline"
          >
            {ingredient.recipe_name}
          </Link>
        </td>
        <td className="py-2.5 pr-4 align-middle">
          {proposal ? (
            <span className="flex items-center gap-1.5 text-sm text-on">
              <Link2 size={14} className="shrink-0 text-primary-600" />
              {proposal.templateName}
            </span>
          ) : (
            <span className="text-sm text-on-muted">
              {t("linking.no_proposal")}
            </span>
          )}
        </td>
        <td className="py-2.5 pr-4 align-middle text-right">
          {canWrite && (
            <IngredientLinkButton
              ingredientId={ingredient.id}
              recipeId={ingredient.recipe_id}
              ingredientName={ingredient.name}
              uomSymbol={ingredient.uom_symbol}
            />
          )}
        </td>
      </tr>
    );
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300 motion-reduce:animate-none">
      {!canWrite && <ReadOnlyNotice module="recipes" />}
      <QueryResult query={unlinkedQuery}>
        {(data) =>
          data.items.length === 0 ? (
            // Nothing to link is "all linked" only when there are
            // ingredients; with none at all the claim would be false.
            !data.hasIngredients ? (
              <EmptyState
                icon={Link2}
                title={t("linking.empty_no_ingredients_title")}
                description={t("linking.empty_no_ingredients_desc")}
              />
            ) : (
              <EmptyState
                icon={CircleCheck}
                title={t("linking.empty_title")}
                description={t("linking.empty_desc")}
              />
            )
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-on-muted">
                  {proposedItems.length > 0
                    ? t("linking.proposed_count", {
                        count: proposedItems.length,
                      })
                    : t("linking.no_proposals_hint")}
                </p>
                {canWrite && (
                  <Button
                    onClick={handleApprove}
                    disabled={selectedCount === 0 || bulkLinkMutation.isPending}
                    leftIcon={
                      bulkLinkMutation.isPending ? (
                        <Loader2 size={16} className="animate-spin" />
                      ) : (
                        <Link2 size={16} />
                      )
                    }
                  >
                    {t("linking.approve_selected", { selected: selectedCount })}
                  </Button>
                )}
              </div>
              <div className="relative rounded-xl border border-border bg-surface-card overflow-x-auto">
                <table className="w-full text-sm">
                  <caption className="sr-only">
                    {t("linking.table_caption")}
                  </caption>
                  <thead>
                    <tr className="border-b border-border bg-surface text-left text-on-muted">
                      <th scope="col" className="py-2.5 pl-4 pr-2">
                        <Checkbox
                          checked={allSelected}
                          indeterminate={selectedCount > 0 && !allSelected}
                          disabled={!canWrite || proposedItems.length === 0}
                          onChange={toggleAll}
                          aria-label={t("linking.select_all")}
                        />
                      </th>
                      <th
                        scope="col"
                        className="py-2.5 pr-4 text-xs font-medium uppercase tracking-wide"
                      >
                        {t("linking.column_ingredient")}
                      </th>
                      <th
                        scope="col"
                        aria-sort="ascending"
                        className="py-2.5 pr-4 text-xs font-medium uppercase tracking-wide"
                      >
                        {t("linking.column_recipe")}
                      </th>
                      <th
                        scope="col"
                        className="py-2.5 pr-4 text-xs font-medium uppercase tracking-wide"
                      >
                        {t("linking.column_product")}
                      </th>
                      <th scope="col" className="py-2.5 pr-4">
                        <span className="sr-only">
                          {t("linking.column_actions")}
                        </span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>{data.items.map(renderRow)}</tbody>
                </table>
              </div>
            </>
          )
        }
      </QueryResult>
    </div>
  );
}
