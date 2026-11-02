import { lazy, Suspense, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CircleHelp } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import DocumentFormModal from "@/modules/warehouse/components/DocumentFormModal";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import { DOCUMENT_DISCREPANCY_CODES } from "@/modules/warehouse/discrepancyCodes";
import type { QuarantineHold } from "@/modules/warehouse/types";

// Opened by a press on Write off only, so a phone loading Start does not pay
// for the dialog, the reason picker and the posting hook it carries.
const WriteOffHoldDialog = lazy(
  () => import("@/modules/warehouse/components/todo/WriteOffHoldDialog"),
);

/** Goods held in quarantine: a batch, or a receipt's batchless quantity.
 *
 * A batch's own screen is where it is released or written off. Goods held
 * without a batch are released by a transfer off the quarantine shelf and
 * written off by a scrap, so the row opens the form that records that
 * decision, with the shelf the goods stand on already chosen. */
function QuarantineDecisionRow({
  hold,
  canWriteItems,
  canWriteDocuments,
}: {
  hold: QuarantineHold;
  canWriteItems: boolean;
  canWriteDocuments: boolean;
}) {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const [formType, setFormType] = useState<"INT" | "SCRAP" | null>(null);
  const [writingOff, setWritingOff] = useState(false);
  const quantity = formatQuantityLocalized(t, hold.quantity, hold.uom_symbol);
  const onHoldShelf = !hold.lot_id && hold.location_name;
  // A receipt's hold carries a discrepancy code; a batch's carries free text.
  const reason =
    hold.reason &&
    (DOCUMENT_DISCREPANCY_CODES as string[]).includes(hold.reason)
      ? t(`detail.discrepancyCodes.${hold.reason}`)
      : hold.reason;
  return (
    <Card className="p-3 sm:p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Link
              to={
                hold.lot_id
                  ? `/inventory/lots/${hold.lot_id}`
                  : `/warehouse/documents/${hold.document_id}`
              }
              className="font-medium text-on break-all hover:text-primary-600"
            >
              {hold.name}
            </Link>
            {hold.product_name && (
              <span className="text-xs text-on-secondary break-words">
                {hold.product_name}
              </span>
            )}
            {quantity && <Badge variant="outline">{quantity}</Badge>}
          </div>
          {hold.reason && (
            <div className="text-xs text-on-secondary mt-0.5 break-words">
              {t("todo.decisionHeldBecause", { reason })}
            </div>
          )}
          {onHoldShelf && (
            <div className="text-xs text-on-secondary mt-0.5 break-words">
              {t("todo.decisionOnShelf", { location: hold.location_name })}
            </div>
          )}
        </div>
        {hold.lot_id
          ? canWriteItems && (
              <Button
                className="max-sm:w-full"
                onClick={() => navigate(`/inventory/lots/${hold.lot_id}`)}
              >
                {t("todo.decisionReviewHold")}
              </Button>
            )
          : canWriteDocuments && (
              <div className="flex flex-wrap gap-2 max-sm:w-full">
                <Button onClick={() => setFormType("INT")}>
                  {t("todo.decisionReleaseHold")}
                </Button>
                <Button
                  variant="outline"
                  // Goods the shelf can name are written off in one step;
                  // the form stays for a hold that cannot say which stock it is.
                  onClick={() =>
                    hold.item_id ? setWritingOff(true) : setFormType("SCRAP")
                  }
                >
                  {t("todo.decisionWriteOff")}
                </Button>
              </div>
            )}
      </div>
      {writingOff && (
        <Suspense fallback={null}>
          <WriteOffHoldDialog
            hold={hold}
            onClose={() => setWritingOff(false)}
          />
        </Suspense>
      )}
      {formType && (
        <DocumentFormModal
          initialType={formType}
          initialSourceLocationId={hold.location_id ?? undefined}
          initialLines={
            hold.item_id
              ? [
                  {
                    item_id: hold.item_id,
                    product_template_id: hold.product_template_id ?? undefined,
                    name: hold.product_name ?? undefined,
                    quantity: hold.quantity,
                  },
                ]
              : undefined
          }
          onClose={() => setFormType(null)}
          onCreated={(created) => {
            setFormType(null);
            navigate(`/warehouse/documents/${created.id}`);
          }}
        />
      )}
    </Card>
  );
}

/**
 * What waits on a person rather than on the floor: goods held in quarantine.
 * Reading it decides nothing — every row is a way into the screen where the
 * release or the write-off is taken.
 */
export function QuarantineBlock({
  holds,
  total,
  canWriteDocuments,
  canWriteItems,
}: {
  holds: QuarantineHold[];
  total: number;
  canWriteDocuments: boolean;
  canWriteItems: boolean;
}) {
  const { t } = useTranslation("warehouse");
  if (total === 0) return null;
  return (
    <section className="space-y-3" aria-label={t("todo.decisionQuarantine")}>
      <div className="flex items-start gap-2">
        <CircleHelp
          size={18}
          className="mt-0.5 shrink-0 text-on-warning"
          aria-hidden="true"
        />
        <div>
          <div className="flex items-baseline gap-2">
            <h2 className="text-base font-semibold text-on">
              {t("todo.decisionQuarantine")}
            </h2>
            <span className="text-sm text-on-secondary tabular-nums">
              {total}
            </span>
          </div>
          <p className="text-xs text-on-secondary mt-0.5">
            {t("todo.decisionsSubtitle")}
          </p>
        </div>
      </div>
      <div className="space-y-2">
        {holds.map((hold) => (
          <QuarantineDecisionRow
            key={
              hold.lot_id ??
              `${hold.document_id}-${hold.product_template_id}-${hold.location_id}`
            }
            hold={hold}
            canWriteItems={canWriteItems}
            canWriteDocuments={canWriteDocuments}
          />
        ))}
      </div>
    </section>
  );
}
