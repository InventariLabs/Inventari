import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import { formatDate, formatMoney } from "@/utils/formatters";
import { POStatusTimeline, type POApprovalTrace } from "./POStatusTimeline";
import type { PurchaseOrder } from "../types/purchase-orders";

interface PODetailsCardProps {
  po: PurchaseOrder;
  partnerName: string | null;
  /** The order's approval request, so the ladder can keep that rung. */
  approval?: POApprovalTrace | null;
}

function Field({
  label,
  value,
  showWhenEmpty = false,
  wide = false,
}: {
  label: string;
  value: string | null;
  /**
   * Render the field with a dash instead of hiding it. A field that is
   * required later reads as "not provided for this order" when it is
   * missing, not as a field this kind of order does not have.
   */
  showWhenEmpty?: boolean;
  /** A sentence rather than a value — the notes take the whole row. */
  wide?: boolean;
}) {
  if (!value && !showWhenEmpty) return null;
  return (
    <div className={wide ? "col-span-2 sm:col-span-4" : undefined}>
      <dt className="text-xs text-on-muted mb-0.5">{label}</dt>
      <dd
        className={
          value ? "text-on break-words whitespace-pre-wrap" : "text-on-muted"
        }
      >
        {value ?? "\u2014"}
      </dd>
    </div>
  );
}

/**
 * The order's metadata, and where it stands.
 *
 * It used to hold two fields next to a document detail that shows a metadata
 * grid, a status axis and dated steps — the same kind of record, told two
 * different ways. Dates, currency and value join the grid, and the
 * axis comes from the same component the document uses.
 *
 * The fields were a label at the left edge and its value at the right one —
 * 1300 px apart on a desktop screen. They take the document's grid now: the
 * label over the value, two columns on a phone and four from `sm` up. The
 * number is the page title, so the grid does not repeat it.
 */
export function PODetailsCard({
  po,
  partnerName,
  approval,
}: PODetailsCardProps) {
  const { t, i18n } = useTranslation(["purchase_orders", "common"]);
  const currency = useDocumentCurrency(po.currency);
  const showDate = (value: string | null) =>
    value ? formatDate(value) : "\u2014";

  return (
    <Card className="p-4 sm:p-6 space-y-5">
      <h2 className="text-sm font-medium text-on-secondary">{t("details")}</h2>
      <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
        <Field label={t("form.partner")} value={partnerName} showWhenEmpty />
        <Field
          label={t("form.scheduledDate")}
          value={showDate(po.scheduled_date)}
        />
        <Field label={t("detail.createdAt")} value={showDate(po.created_at)} />
        <Field
          label={t("detail.confirmedAt")}
          value={po.confirmed_at ? showDate(po.confirmed_at) : null}
        />
        <Field label={t("detail.currency")} value={currency ?? null} />
        <Field
          label={t("detail.total")}
          value={
            po.total_gross == null
              ? t("noPriceYet")
              : formatMoney(po.total_gross, currency, i18n.language)
          }
        />
        <Field label={t("form.notes")} value={po.notes} wide />
      </dl>

      <POStatusTimeline po={po} approval={approval} formatDate={showDate} />
    </Card>
  );
}
