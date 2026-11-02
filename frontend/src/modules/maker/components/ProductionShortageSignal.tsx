import { useTranslation } from "react-i18next";

/**
 * The one shortage signal the list shows — on a grid card and in a table
 * row alike.
 *
 * The detail page calls a draft's shortage a blocker: "completing this run
 * will be refused". A card that said nothing about it made the planner open
 * drafts one by one to learn which ones would be refused. The count is the
 * server's — the same function completion refuses with, at the order's own
 * output location — so the list, the detail page and the refusal cannot
 * disagree.
 */
export function ProductionShortageSignal({
  count,
  className,
}: {
  count: number | null | undefined;
  className?: string;
}) {
  const { t } = useTranslation("maker");
  if (typeof count !== "number" || count <= 0) return null;
  return (
    <div
      className={`text-xs mt-1 font-medium text-red-600 dark:text-red-400 ${
        className ?? ""
      }`}
      data-testid="maker-order-shortage"
    >
      {t("productionList.card.shortage", { count })}
    </div>
  );
}
