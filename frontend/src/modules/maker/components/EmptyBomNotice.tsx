import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";
import { Card } from "@/components/ui/Card";

interface EmptyBomNoticeProps {
  /** When known, the notice links to the composition tab that can fix it. */
  recipeId?: string | null;
  className?: string;
}

/**
 * "This BOM lists no ingredients."
 *
 * The backend refuses such a run — completing it would create the output
 * against zero consumption — but it only gets to say so at the last step, four
 * screens in, after the confirmation that warns the operation cannot be
 * undone. Every screen before that had the same fact in its own data and said
 * nothing: the cost preview rendered an empty ingredient section, and the
 * pricing calculator quoted a sale price of zero, which is what a 30% margin
 * on nothing comes to.
 *
 * One component and one key, so the three of them cannot drift into three
 * wordings of the same sentence.
 */
export function EmptyBomNotice({ recipeId, className }: EmptyBomNoticeProps) {
  const { t } = useTranslation("maker");

  return (
    <Card
      className={`p-4 bg-amber-50 text-on-warning text-sm flex items-start gap-3 ${className ?? ""}`}
      role="alert"
    >
      <AlertTriangle size={18} className="mt-0.5 shrink-0" />
      <div>
        <p>{t("detail.emptyBom")}</p>
        {recipeId && (
          <Link
            to={`/maker/recipes/${recipeId}`}
            className="mt-1 inline-block font-semibold underline"
          >
            {t("detail.emptyBomAction")}
          </Link>
        )}
      </div>
    </Card>
  );
}
