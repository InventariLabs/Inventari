import type { TFunction } from "i18next";
import type { AttentionItem } from "@/components/ui/AttentionCard";
import { formatDate } from "@/utils/helpers";
import type { EquipmentAssetItem } from "@/modules/equipment/api/equipment_assets";
import type { OverdueAssignmentItem } from "@/modules/equipment/api/equipment_assignments";
import type { WarrantyAlert } from "@/modules/equipment/api/equipment_dashboard";
import {
  getEquipmentMeta,
  unitIdentifier,
} from "@/modules/equipment/components/assetUtils";

interface FleetAttentionSources {
  overdue: readonly OverdueAssignmentItem[];
  warrantyEnding: readonly WarrantyAlert[];
  warrantyExpired: readonly WarrantyAlert[];
  /** Assets in maintenance with nobody holding them. */
  inService: readonly EquipmentAssetItem[];
}

/** "OptiPlex 7010 · SN-0001": the model names a kind, the number a unit. */
function unitTitle(name: string, identifier: string | null) {
  return identifier ? `${name} · ${identifier}` : name;
}

/**
 * The equipment overview's attention rows. Sources are taken most urgent
 * first and an asset is counted once, under the first reason it turns up
 * with: a late return, then an ending warranty, then a stay in service, and
 * a warranty already over last — a fact to know, not a thing to do today.
 */
export function toFleetAttention(
  sources: FleetAttentionSources,
  t: TFunction,
): AttentionItem[] {
  const rows: AttentionItem[] = [];
  const seen = new Set<string>();
  const add = (row: AttentionItem) => {
    if (seen.has(row.id)) return;
    seen.add(row.id);
    rows.push(row);
  };

  for (const o of sources.overdue) {
    add({
      id: o.item_id,
      severity: "expired",
      title: unitTitle(o.item_name, unitIdentifier(o)),
      reason:
        o.days_overdue > 0
          ? t("equipment:dashboard.attention.return_overdue_days", {
              count: o.days_overdue,
            })
          : t("equipment:dashboard.attention.return_overdue"),
      where: o.holder_name ?? undefined,
      href: `/equipment/${o.item_id}`,
    });
  }
  for (const w of sources.warrantyEnding) {
    add({
      id: w.item_id,
      severity: "expiring",
      title: unitTitle(w.item_name, w.serial_number),
      // Zero days is a date word, not a number.
      reason:
        w.days_remaining === 0
          ? t("equipment:dashboard.attention.warranty_ends_today")
          : t("equipment:dashboard.attention.warranty_ends", {
              count: w.days_remaining,
            }),
      where: w.assigned_to ?? undefined,
      href: `/equipment/${w.item_id}`,
    });
  }
  for (const a of sources.inService) {
    const meta = getEquipmentMeta(a);
    add({
      id: a.id,
      severity: "low",
      title: unitTitle(a.name, meta.serial_number ?? meta.asset_tag),
      reason: t("equipment:dashboard.attention.in_service"),
      where: a.location_name ?? undefined,
      href: `/equipment/${a.id}`,
    });
  }
  for (const w of sources.warrantyExpired) {
    add({
      id: w.item_id,
      severity: "info",
      title: unitTitle(w.item_name, w.serial_number),
      reason: t("equipment:dashboard.attention.warranty_ended", {
        date: formatDate(w.warranty_until),
      }),
      where: w.assigned_to ?? undefined,
      href: `/equipment/${w.item_id}`,
    });
  }
  return rows;
}
