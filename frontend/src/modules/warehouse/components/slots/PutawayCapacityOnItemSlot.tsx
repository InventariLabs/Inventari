import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { Badge } from "@/components/ui/Badge";
import { formatQuantityLocale } from "@/utils/formatters";
import {
  putawayCapacityApi,
  type PutawayCapacityEntry,
} from "@/modules/warehouse/api/putaway";
import type { Item } from "@/types";
import { useStorageLocationLabels } from "@/modules/shared/hooks/useStorageLocationLabels";

/**
 * The capacity sentence on a product's page: "A-12 mieści 200".
 *
 * The item names a shelf and a catalogue product; the capacity is the
 * warehouse module's answer about that pair. Nothing renders when nobody
 * set a limit — an unlimited shelf is the org-wide default and saying so
 * on every product page would be noise.
 */
export default function PutawayCapacityOnItemSlot({
  data,
}: {
  data: { item: Item };
}) {
  const { t } = useTranslation("warehouse");
  const templateId = data.item.template_id;
  const locationId = data.item.location_id;

  // Named by path: the sentence stands on a product's page, where a bare
  // "Shelf 1" does not say which warehouse's.
  const placeName = useStorageLocationLabels([locationId]);

  const { data: entries } = useQuery({
    queryKey: queryKeys.documents.putawayCapacity(locationId),
    queryFn: () => putawayCapacityApi.list({ location_id: locationId! }),
    enabled: Boolean(templateId && locationId),
  });

  if (!templateId || !locationId) return null;
  const entry: PutawayCapacityEntry | undefined = entries?.find(
    (e) => e.product_template_id === templateId,
  );
  if (!entry) return null;

  return (
    <div className="text-sm text-on-secondary">
      {t("putaway.capacity.holdsAt", {
        location: placeName(entry.location_id, entry.location_name) ?? "",
        max: formatQuantityLocale(entry.max_quantity),
      })}
      {entry.reorder_over_capacity && (
        <Badge variant="warning" className="ml-2">
          {t("putaway.capacity.overReorder", {
            reorder: formatQuantityLocale(entry.reorder_max_quantity ?? ""),
          })}
        </Badge>
      )}
    </div>
  );
}
