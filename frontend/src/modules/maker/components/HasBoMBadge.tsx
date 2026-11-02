import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ClipboardList } from "lucide-react";
import { useBomSummary } from "@/modules/maker/hooks/useBom";

/**
 * Badge shown in the items table for products that have a Bill of Materials.
 *
 * It carries no word of its own, and that is the point. Every language had it
 * printing a bare noun — "Receptura", "Formel", "Fórmula" — in a cell next to
 * a product name, and a noun in that position names the row: the jam produced
 * by a closed order read as a formula sitting in the stock list. What the
 * column means is already written in its header; the cell only has to answer
 * yes, which the icon does, and offer the way through, which the accessible
 * name does.
 *
 * The table is virtualized, so only visible rows mount the badge; the summary
 * query is cached (staleTime 60s), keeping repeat renders cheap.
 *
 * Clicking the badge navigates to the default recipe card
 * (`/maker/recipes/{default_recipe_id}`). The badge only shows for products
 * that already have BoM lines, but those lines can sit on a non-default
 * formula, leaving no default to open — then it falls back to the catalog
 * rather than the removed `/maker/bom` editor.
 */
export function HasBoMBadge({ templateId }: { templateId: string }) {
  const { t } = useTranslation("maker");
  const { data } = useBomSummary(templateId);
  const entry = data?.items.find((i) => i.template_id === templateId);
  if (!entry) return null;

  const to = entry.default_recipe_id
    ? `/maker/recipes/${entry.default_recipe_id}`
    : "/maker";

  return (
    <Link
      to={to}
      className="inline-flex items-center text-accent-700 bg-accent-50 rounded p-1 hover:bg-accent-100 transition-colors"
      aria-label={t("bomEntry.openRecipe")}
      title={t("bomEntry.openRecipe")}
      data-testid="maker-has-bom-badge"
    >
      <ClipboardList size={14} aria-hidden="true" />
    </Link>
  );
}
