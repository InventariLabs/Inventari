import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BookOpen } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useCanManage } from "@/hooks/useCanWrite";
import type { ProductOption } from "@/modules/maker/api/products";

interface MissingRecipeNoticeProps {
  /**
   * The output product the formula is missing for. Given, the notice opens
   * the catalog's create sheet already pointed at it; without it, it goes
   * to the catalog and the reader picks the product there.
   */
  product?: ProductOption | null;
  className?: string;
}

/**
 * "This product has no formula."
 *
 * The cost preview and the pricing calculator used to render the empty-BOM
 * notice here — a sentence claiming a recipe exists and waits for
 * ingredients, on a product that has no recipe at all, while the create
 * button beside it answered "no recipe for this product". The two truths
 * share a shape (zero entries, a total of 0.00) and nothing else: this one
 * leads where a formula is created, the empty one where a formula is
 * filled.
 */
export function MissingRecipeNotice({
  product,
  className,
}: MissingRecipeNoticeProps) {
  const { t } = useTranslation("maker");
  // Formulas are the manager's to write; for anyone else the link would lead
  // to a sheet that cannot be saved.
  const canManage = useCanManage("maker");

  return (
    <Card
      className={`p-4 bg-amber-50 text-on-warning text-sm flex items-start gap-3 ${className ?? ""}`}
      role="alert"
    >
      <BookOpen size={18} className="mt-0.5 shrink-0" />
      <div>
        <p>{t("detail.noBom")}</p>
        {canManage && (
          <Link
            to="/maker"
            state={product ? { createRecipeFor: product } : undefined}
            className="mt-1 inline-block font-semibold underline"
            data-testid="missing-recipe-create-link"
          >
            {t("detail.noBomAction")}
          </Link>
        )}
      </div>
    </Card>
  );
}
