import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CheckCircle, FileCheck } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { useModules } from "@/contexts/ModulesContext";
import type { StockTakeReport } from "../types/stock-takes";

/**
 * What closing the count left behind: the stock adjustment its differences
 * posted as, or — when every counted row matched — that it was counted and
 * nothing had to change. A count still open, or one whose differences went
 * nowhere (the warehouse module off, or closed before the register kept
 * them), says nothing here.
 */
export default function StockTakePostingNote({
  report,
}: {
  report: StockTakeReport;
}) {
  const { t } = useTranslation("stock_takes");
  const { isModuleEnabled } = useModules();
  if (report.status !== "completed") return null;
  const number = report.adjustment_document_number;
  if (report.adjustment_document_id && number) {
    return (
      <Card className="flex items-center gap-3 p-4">
        <FileCheck size={20} className="shrink-0 text-on-muted" />
        <p className="text-sm text-on">
          {t("posting.adjusted")}{" "}
          {isModuleEnabled("warehouse") ? (
            <Link
              to={`/warehouse/documents/${report.adjustment_document_id}`}
              className="font-medium text-primary-600 hover:text-primary-700 hover:underline"
            >
              {number}
            </Link>
          ) : (
            <span className="font-medium">{number}</span>
          )}
        </p>
      </Card>
    );
  }
  if (
    report.counted_items > 0 &&
    report.perfect_matches === report.counted_items
  )
    return (
      <Card className="flex items-center gap-3 p-4">
        <CheckCircle size={20} className="shrink-0 text-on-success" />
        <p className="text-sm text-on">{t("posting.noDifferences")}</p>
      </Card>
    );
  return null;
}
