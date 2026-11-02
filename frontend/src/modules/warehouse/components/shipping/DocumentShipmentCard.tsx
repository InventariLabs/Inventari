import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Truck } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { formatDateTime } from "@/utils/formatters";
import type { DocumentShipment } from "@/modules/warehouse/api/shipments";
import { TrackingLink } from "./TrackingLink";

interface Props {
  /** The document's shipment; a document that never shipped shows no card. */
  shipment?: DocumentShipment | null;
}

/**
 * The hand-over a completed dispatch recorded: who took the parcels, the
 * number to follow them by, how many there were, and when and by whom they
 * left. The question asked of a dispatch a week later is "where is it", and
 * this card is the answer without leaving the page.
 */
export function DocumentShipmentCard({ shipment }: Props) {
  const { t } = useTranslation("warehouse");
  if (!shipment) return null;
  // A carrier's number runs to 20-odd digits with no space to break at: on a
  // phone's half-width column it may break anywhere rather than run past the
  // card's edge.
  const field = (label: string, value: ReactNode) => (
    <div className="min-w-0">
      <dt className="text-xs text-on-muted mb-0.5">{label}</dt>
      <dd className="text-sm text-on [overflow-wrap:anywhere]">{value}</dd>
    </div>
  );

  return (
    <Card className="p-4 sm:p-5 space-y-3">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-on">
        <Truck size={18} className="text-on-secondary" aria-hidden="true" />
        {t("shipping.cardTitle")}
      </h2>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        {field(t("shipping.carrier"), shipment.carrier)}
        {field(
          t("shipping.trackingNumber"),
          <TrackingLink
            trackingNumber={shipment.tracking_number}
            trackingUrl={shipment.tracking_url}
          />,
        )}
        {field(t("shipping.packages"), shipment.package_count ?? 0)}
        {field(t("shipping.shippedAt"), formatDateTime(shipment.shipped_at))}
        {field(t("shipping.shippedBy"), shipment.shipped_by_name ?? "—")}
      </dl>
      {shipment.notes && (
        <p className="text-sm text-on-secondary whitespace-pre-line">
          {shipment.notes}
        </p>
      )}
    </Card>
  );
}
