import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import StockTakeProgress from "./StockTakeProgress";

/**
 * What an account that may read a count but not take it sees: the notice,
 * how far the count got and, once it is finished, the way to its report. The
 * notice alone left a page with a title and nothing to do or see.
 */
export default function StockTakeReadOnlyView({
  stockTakeId,
  completed,
  countedCount,
  totalCount,
  progress,
  discrepanciesCount,
}: {
  stockTakeId: string;
  completed: boolean;
  countedCount: number;
  totalCount: number;
  progress: number;
  discrepanciesCount: number;
}) {
  const { t } = useTranslation("stock_takes");
  return (
    <div className="space-y-4">
      <ReadOnlyNotice module="stock_takes" />
      <StockTakeProgress
        countedCount={countedCount}
        totalCount={totalCount}
        progress={progress}
        discrepanciesCount={discrepanciesCount}
        unsavedCount={0}
      />
      {completed && (
        <Link to={`/inventory/stock-takes/${stockTakeId}/report`}>
          <Button variant="outline" rightIcon={<ChevronRight size={14} />}>
            {t("report.title")}
          </Button>
        </Link>
      )}
    </div>
  );
}
