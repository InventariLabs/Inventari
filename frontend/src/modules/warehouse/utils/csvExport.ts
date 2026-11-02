import { toCsv } from "@/lib/csv";
import type { WarehouseDocumentRow } from "@/modules/warehouse/types";

type TFunc = (key: string, options?: Record<string, unknown>) => string;

export function exportDocumentsCsv(
  docs: WarehouseDocumentRow[],
  t: TFunc,
): string {
  const header = [
    t("warehouse:bulk.csv.number"),
    t("warehouse:bulk.csv.type"),
    t("warehouse:bulk.csv.status"),
    t("warehouse:bulk.csv.partner"),
    t("warehouse:bulk.csv.createdAt"),
    t("warehouse:bulk.csv.total"),
  ];
  const rows = docs.map((d) => [
    d.number,
    d.type,
    d.status,
    d.partner_snapshot?.name ?? "",
    d.created_at,
    d.total_gross ?? d.total_net ?? "",
  ]);
  return toCsv([header, ...rows]);
}
