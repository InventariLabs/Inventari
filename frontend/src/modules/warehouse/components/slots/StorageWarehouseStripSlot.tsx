import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useCanWrite } from "@/hooks/useCanWrite";
import { queryKeys } from "@/hooks/queries/keys";
import { api } from "@/lib/api/client";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import {
  putawayCapacityApi,
  type PutawayOccupancy,
} from "@/modules/warehouse/api/putaway";
import { ShelfSettingsSheet } from "@/modules/warehouse/components/ShelfSettingsSheet";

/**
 * How the warehouse treats a place, in one read-only line on the location's
 * Settings tab: "walk order 15 · different products · limit: Rice — 40 pcs ·
 * 23%". Its button opens the panel of the Locations tab, so there is one form
 * for these facts and this is only the way to it from Inventory.
 *
 * A slot, not an import: the facts belong to this module and the page to
 * Spaces. With the module off the slot has no contributor and the page shows
 * nothing in its place.
 */
export default function StorageWarehouseStripSlot({
  data,
}: {
  data: SlotDataMap["storage_warehouse_strip"];
}) {
  const { t } = useTranslation("warehouse");
  const canWrite = useCanWrite("warehouse");
  const canWriteStorages = useCanWrite("locations");
  // A custom role can grant storages without documents; the reads below
  // would then fail and leave an error card in the line's place.
  const mayRead = useHasPermission("warehouse:read");
  const [panelOpen, setPanelOpen] = useState(false);

  // The same keys the panel invalidates on Save, so the strip follows it.
  const limits = useQuery({
    queryKey: queryKeys.documents.putawayCapacity(data.storageId),
    queryFn: () => putawayCapacityApi.list({ location_id: data.storageId }),
    enabled: mayRead,
  });
  const setting = useQuery({
    queryKey: queryKeys.documents.putawayCapacitySetting(data.storageId),
    queryFn: () => putawayCapacityApi.getSetting(data.storageId),
    enabled: mayRead,
  });
  const occupancy = useQuery({
    queryKey: queryKeys.documents.putawayOccupancy(data.storageId),
    queryFn: async (): Promise<PutawayOccupancy> => {
      const response = await api.get<PutawayOccupancy>(
        `/warehouse/putaway/occupancy/${data.storageId}`,
      );
      return response.data;
    },
    enabled: mayRead,
  });

  if (!mayRead) return null;
  const failed = [limits, setting, occupancy].find((query) => query.isError);
  if (failed) {
    return (
      <Card>
        <QueryFailure
          error={failed.error}
          message={t("errors.loadShelfSettingsFailed")}
          onRetry={() => void failed.refetch()}
        />
      </Card>
    );
  }
  if (!limits.data || !setting.data || !occupancy.data) return null;

  // The panel is for this place alone; the occupancy read also lists
  // everything inside it.
  const fill =
    occupancy.data.locations.find((cell) => cell.location_id === data.storageId)
      ?.fill ?? null;
  const [only] = limits.data;

  const parts = [
    data.sequence == null
      ? t("putaway.locations.strip.walkOrderNone")
      : t("putaway.locations.strip.walkOrder", { order: data.sequence }),
    setting.data.single_product
      ? t("putaway.locations.strip.single")
      : t("putaway.locations.strip.mixed"),
    limits.data.length === 0
      ? t("putaway.locations.strip.noLimit")
      : limits.data.length === 1
        ? t("putaway.locations.strip.oneLimit", {
            product: only.product_template_name ?? "—",
            max: formatQuantityLocalized(
              t,
              only.max_quantity,
              only.product_unit_symbol,
            ),
          })
        : t("putaway.locations.strip.limits", { count: limits.data.length }),
  ];
  if (fill !== null) parts.push(`${fill}%`);

  return (
    <Card className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-on">
        <span className="font-semibold">
          {t("putaway.locations.strip.label")}
        </span>{" "}
        <span className="text-on-secondary">{parts.join(" · ")}</span>
      </p>
      <Button variant="outline" size="sm" onClick={() => setPanelOpen(true)}>
        {t("putaway.locations.strip.setUp")}
      </Button>
      {panelOpen && (
        <ShelfSettingsSheet
          location={{
            id: data.storageId,
            name: data.storageName,
            sequence: data.sequence,
            full_path: data.fullPath,
          }}
          canWrite={canWrite}
          canWriteStorages={canWriteStorages}
          onClose={() => setPanelOpen(false)}
        />
      )}
    </Card>
  );
}
