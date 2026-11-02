import { Card } from "@/components/ui/Card";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import type { POLine } from "@/modules/purchase_orders/types/purchase-orders";
import {
  formatMoney,
  formatPercentLocale,
  formatQuantityValue,
} from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";

type Translate = (key: string, options?: Record<string, unknown>) => string;

interface POLinesCardProps {
  lines: POLine[];
  poNet: number;
  poTax: number;
  poTotal: number;
  /** False when a line has no price: the footer then has no sums to print. */
  totalKnown?: boolean;
  currency?: string | null;
  locale?: string;
  /** The order status — a draft has nothing received, so no progress bar. */
  status?: string;
  t: Translate;
}

/** One line's numbers, read off the wire's strings once. */
interface LineFigures {
  line: POLine;
  qty: number;
  received: number;
  taxRate: number;
  net: number;
  tax: number;
  gross: number;
}

function figuresOf(line: POLine): LineFigures {
  const qty = Number(line.quantity_ordered) || 0;
  const received = Number(line.quantity_received) || 0;
  const price = Number(line.unit_price) || 0;
  const taxRate = Number(line.tax_rate) || 0;
  const net = qty * price;
  const tax = (net * taxRate) / 100;
  return { line, qty, received, taxRate, net, tax, gross: net + tax };
}

/**
 * How much of the line arrived: both numbers, and a meter while some is
 * still missing. A bare bar answered "how far along" with a sliver and
 * nothing else.
 */
function ReceivedProgress({
  figures,
  t,
}: {
  figures: LineFigures;
  t: Translate;
}) {
  const { line, qty, received } = figures;
  return (
    <div className="inline-flex items-center gap-2">
      <span className="text-xs text-on-secondary tabular-nums">
        {formatQuantityValue(line.quantity_received)}/
        {formatQuantityValue(line.quantity_ordered)}
      </span>
      {received < qty && (
        <div
          role="meter"
          aria-valuemin={0}
          aria-valuemax={qty}
          aria-valuenow={received}
          aria-label={t("receivedProgress", {
            ns: "purchase_orders",
            received: formatQuantityValue(line.quantity_received),
            ordered: formatQuantityValue(line.quantity_ordered),
          })}
          className="h-1.5 w-16 rounded-full bg-border overflow-hidden"
        >
          <div
            className="h-full bg-accent-500 rounded-full"
            style={{ width: `${Math.min(100, (received / qty) * 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}

const th = "px-4 py-2.5 text-xs font-medium text-on-muted";

/**
 * The lines as columns, the way the document detail lays out its own.
 *
 * Each line used to be a sentence — the name at the left edge, and at the
 * right one "4 200,00 zł / szt. = 20 664,00 zł (Netto: 16 800,00 zł + 23,0%
 * = 3 864,00 zł)", whose second half read as if the net plus the rate came
 * to the tax. The net, the tax and the total each have a column now.
 */
function LinesTable({
  rows,
  showReceived,
  money,
  t,
}: {
  rows: LineFigures[];
  showReceived: boolean;
  money: (value: number) => string;
  t: Translate;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left border-b border-border bg-surface-raised/50">
            <th scope="col" className={`${th} w-8`}>
              #
            </th>
            <th scope="col" className={th}>
              {t("form.lineProduct", { ns: "purchase_orders" })}
            </th>
            <th scope="col" className={`${th} text-right`}>
              {t("form.lineQuantity", { ns: "purchase_orders" })}
            </th>
            <th scope="col" className={`${th} text-right`}>
              {t("form.lineUnitPrice", { ns: "purchase_orders" })}
            </th>
            <th scope="col" className={`${th} text-right`}>
              {t("form.net", { ns: "purchase_orders" })}
            </th>
            <th scope="col" className={`${th} text-right`}>
              {t("form.taxAmount", { ns: "purchase_orders" })}
            </th>
            <th scope="col" className={`${th} text-right`}>
              {t("form.total", { ns: "purchase_orders" })}
            </th>
            {showReceived && (
              <th scope="col" className={`${th} text-right`}>
                {t("received", { ns: "purchase_orders" })}
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.map((figures) => {
            const { line } = figures;
            return (
              <tr
                key={line.id}
                className="border-b border-border last:border-b-0"
              >
                <td className="px-4 py-3 text-xs text-on-muted">
                  {line.line_number}
                </td>
                <td className="px-4 py-3">
                  <div className="font-medium text-on">{line.name}</div>
                  {line.product_template_id && (
                    <div className="text-xs text-on-secondary">
                      {t("form.productLinked", { ns: "purchase_orders" })}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-right tabular-nums whitespace-nowrap">
                  <span className="font-medium">
                    {formatQuantityValue(line.quantity_ordered)}
                  </span>{" "}
                  <span className="text-xs text-on-secondary">
                    {unitLabel(t, line.uom_symbol) ||
                      t("units", { ns: "purchase_orders" })}
                  </span>
                </td>
                <td className="px-4 py-3 text-right tabular-nums whitespace-nowrap">
                  {line.unit_price ? money(Number(line.unit_price)) : "—"}
                </td>
                <td className="px-4 py-3 text-right tabular-nums whitespace-nowrap">
                  {line.unit_price ? money(figures.net) : "—"}
                </td>
                <td className="px-4 py-3 text-right tabular-nums whitespace-nowrap">
                  {line.unit_price && figures.taxRate > 0 ? (
                    <>
                      <div>{money(figures.tax)}</div>
                      {/* The wire's Decimal stays a string here on purpose:
                          it is the rate as written, and Number() would strip
                          the digits a fractional rate carries ("20,8%" for
                          20.75). */}
                      <div className="text-xs text-on-secondary">
                        {formatPercentLocale(line.tax_rate, 1)}
                      </div>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-3 text-right tabular-nums whitespace-nowrap font-medium text-on">
                  {line.unit_price ? money(figures.gross) : "—"}
                </td>
                {showReceived && (
                  <td className="px-4 py-3 text-right">
                    <ReceivedProgress figures={figures} t={t} />
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** On a phone seven columns do not fit; each line is a short block. */
function LinesList({
  rows,
  showReceived,
  money,
  t,
}: {
  rows: LineFigures[];
  showReceived: boolean;
  money: (value: number) => string;
  t: Translate;
}) {
  return (
    <ul className="divide-y divide-border">
      {rows.map((figures) => {
        const { line } = figures;
        return (
          <li key={line.id} className="px-4 py-3 space-y-1 text-sm">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="font-medium text-on break-words">
                  {line.line_number}. {line.name}
                </div>
                <div className="text-xs text-on-secondary tabular-nums">
                  <span>{formatQuantityValue(line.quantity_ordered)}</span>{" "}
                  <span>
                    {unitLabel(t, line.uom_symbol) ||
                      t("units", { ns: "purchase_orders" })}
                  </span>
                  {line.unit_price && (
                    <> &times; {money(Number(line.unit_price))}</>
                  )}
                </div>
              </div>
              <div className="shrink-0 font-medium text-on tabular-nums">
                {line.unit_price ? money(figures.gross) : "—"}
              </div>
            </div>
            {line.unit_price && figures.taxRate > 0 && (
              <div className="text-xs text-on-secondary tabular-nums">
                {t("form.net", { ns: "purchase_orders" })} {money(figures.net)}{" "}
                &middot; {t("form.taxAmount", { ns: "purchase_orders" })}{" "}
                {formatPercentLocale(line.tax_rate, 1)} {money(figures.tax)}
              </div>
            )}
            {showReceived && <ReceivedProgress figures={figures} t={t} />}
          </li>
        );
      })}
    </ul>
  );
}

export function POLinesCard({
  lines,
  poNet,
  poTax,
  poTotal,
  totalKnown = true,
  currency,
  locale,
  status,
  t,
}: POLinesCardProps) {
  const isPhone = useMediaQuery("(max-width: 639px)");
  // Receiving only becomes possible once the order is confirmed; a progress
  // bar at 0% on a draft said "nothing arrived" without saying that nothing
  // could have arrived yet.
  const showReceived = status === "CONFIRMED" || status === "COMPLETED";
  const money = (value: number) => formatMoney(value, currency, locale);
  const rows = lines.map(figuresOf);
  const Lines = isPhone ? LinesList : LinesTable;

  return (
    <Card className="overflow-hidden">
      <div className="px-4 sm:px-6 py-3 border-b border-border">
        <h2 className="text-sm font-medium text-on-secondary">
          {t("linesTitle", { ns: "purchase_orders", count: lines.length })}
        </h2>
      </div>
      <Lines rows={rows} showReceived={showReceived} money={money} t={t} />
      {/* reading order matches understanding — totals come after
          the lines they summarize, separated like on a paper document. */}
      {!totalKnown && (
        <div className="border-t border-border px-4 sm:px-6 py-3">
          <div className="ml-auto flex max-w-xs justify-between gap-6 text-sm">
            <span className="text-on-secondary">
              {t("form.total", { ns: "purchase_orders" })}:
            </span>
            <span className="text-on-muted">
              {t("noPriceYet", { ns: "purchase_orders" })}
            </span>
          </div>
        </div>
      )}
      {totalKnown && poNet > 0 && (
        <div className="border-t border-border px-4 sm:px-6 py-3">
          <div className="ml-auto max-w-xs space-y-1 text-sm">
            <div className="flex justify-between gap-6">
              <span className="text-on-secondary">
                {t("form.net", { ns: "purchase_orders" })}:
              </span>
              <span className="font-medium tabular-nums">{money(poNet)}</span>
            </div>
            {poTax > 0 && (
              <div className="flex justify-between gap-6">
                <span className="text-on-secondary">
                  {t("form.taxAmount", { ns: "purchase_orders" })}:
                </span>
                <span className="font-medium tabular-nums">{money(poTax)}</span>
              </div>
            )}
            <div className="flex justify-between gap-6 border-t border-border pt-1">
              <span className="text-on-secondary">
                {t("form.total", { ns: "purchase_orders" })}:
              </span>
              <span className="font-semibold tabular-nums">
                {money(poTotal)}
              </span>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
