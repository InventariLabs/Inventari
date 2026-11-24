import { useTranslation } from "react-i18next";
import { formatDate } from "@/utils/helpers";
import { runDay } from "@/modules/maker/lib/runDay";
import type { ProductionOrder } from "@/modules/maker/types/maker";

/** The day a run card or row shows, worded for what the day is. */
export function RunDayText({ order }: { order: ProductionOrder }) {
  const { t } = useTranslation("maker");
  const { day, kind } = runDay(order);
  const date = formatDate(day);
  if (kind === "planned")
    return <>{t("productionList.card.plannedFor", { date })}</>;
  if (kind === "started")
    return <>{t("productionList.card.startedOn", { date })}</>;
  return <>{date}</>;
}
