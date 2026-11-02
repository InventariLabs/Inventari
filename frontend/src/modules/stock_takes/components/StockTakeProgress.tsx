import { useTranslation } from "react-i18next";
import { AlertTriangle } from "lucide-react";

interface Props {
  countedCount: number;
  totalCount: number;
  progress: number;
  discrepanciesCount: number;
  unsavedCount: number;
}

/**
 * How far the count has got — measured in rows the stock take holds.
 *
 * The bar used to move on a number typed into a box, which is work that
 * disappears on the way out of the screen. It now moves on saves, and the
 * numbers still waiting in their boxes are named beside it rather than
 * counted into it.
 */
export default function StockTakeProgress({
  countedCount,
  totalCount,
  progress,
  discrepanciesCount,
  unsavedCount,
}: Props) {
  const { t } = useTranslation(["stock_takes"]);
  return (
    <div className="bg-surface-card rounded-xl p-4 border shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-on-secondary">
          {t("progress.title")}
        </span>
        <span className="text-sm text-on-secondary">
          {t("progress.countedOf", {
            counted: countedCount,
            total: totalCount,
          })}
        </span>
      </div>
      {unsavedCount > 0 && (
        <div className="text-sm text-primary-700 mb-2">
          {t("progress.unsaved", { count: unsavedCount })}
        </div>
      )}
      <div className="w-full bg-surface-inset rounded-full h-3">
        <div
          className={`h-3 rounded-full transition-all ${progress === 100 ? "bg-accent-500" : "bg-primary-500"}`}
          style={{ width: `${progress}%` }}
        />
      </div>
      {discrepanciesCount > 0 && (
        <div className="flex items-center gap-2 mt-2 text-sm text-on-warning">
          <AlertTriangle size={16} />
          <span>
            {t("progress.discrepanciesDetected", { count: discrepanciesCount })}
          </span>
        </div>
      )}
    </div>
  );
}
