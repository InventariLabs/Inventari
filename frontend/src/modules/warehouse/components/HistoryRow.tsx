import { documentTitle } from "@/modules/warehouse/lib/documentTitle";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { DocumentStatusBadge } from "@/modules/warehouse/components/DocumentStatusBadge";
import { describeHistoryEntry } from "@/modules/warehouse/historyEntry";
import {
  showsDocumentValue,
  type WarehouseDocumentRow,
} from "@/modules/warehouse/types";
import { cn } from "@/lib/utils";
import { formatDateTime, formatMoney } from "@/utils/formatters";
import type { DocumentColumnContributor } from "@/lib/moduleRegistry";
import {
  toDocumentView,
  type FromModule,
} from "@/modules/warehouse/hooks/useDocumentContributions";

/** The row's columns at desktop width, a module's own among them. */
function gridColumns(tracksValue: boolean, extra: number): string {
  return [
    "8rem minmax(0,1fr) 9rem 6rem",
    ...Array.from({ length: extra }, () => "minmax(0,9rem)"),
    ...(tracksValue ? ["6rem"] : []),
  ].join(" ");
}

interface HistoryRowProps {
  doc: WarehouseDocumentRow;
  /**
   * The organization tracks the value of stock, so the list has an amount
   * column. Every row keeps the column — a transfer holds a dash in it —
   * because a row with one track fewer put its author and document 6rem
   * further right than the rows around it.
   */
  tracksValue: boolean;
  /**
   * Columns enabled modules add, already narrowed by the page to the ones
   * some row on it fills.
   */
  columns?: FromModule<DocumentColumnContributor>[];
}

/**
 * One entry of the History list: what happened in a sentence, the document
 * that proves it, who did it and — where value is tracked — what it was worth.
 */
export function HistoryRow({
  doc,
  tracksValue,
  columns = [],
}: HistoryRowProps) {
  const { t, i18n } = useTranslation("warehouse");
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const { sentence, detail } = describeHistoryEntry(doc, t);
  // Only a document whose lines carry a price has an amount to quote.
  const quotesAmount = showsDocumentValue(doc.type, tracksValue);
  const completed = doc.status === "COMPLETED";
  // The moment it was done, or for work not done yet the moment it was typed.
  const when = formatDateTime(
    completed ? (doc.completed_at ?? doc.created_at) : doc.created_at,
  );
  const who =
    (completed ? doc.completed_by_name : null) ??
    doc.confirmed_by_name ??
    doc.created_by_name;

  return (
    <li
      className={cn(
        "flex flex-col gap-1 px-4 py-3 sm:grid sm:items-start sm:gap-x-3",
        tracksValue
          ? "sm:grid-cols-[8rem_minmax(0,1fr)_9rem_6rem_6rem]"
          : "sm:grid-cols-[8rem_minmax(0,1fr)_9rem_6rem]",
      )}
      // A module's column widens the grid by one track; the template is
      // only read at desktop width, where the row is a grid at all.
      style={
        columns.length > 0
          ? { gridTemplateColumns: gridColumns(tracksValue, columns.length) }
          : undefined
      }
    >
      <span className="text-xs text-on-secondary tabular-nums sm:pt-0.5">
        {when}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="text-sm text-on">{sentence}</span>
        {detail && <span className="text-xs text-on-secondary">{detail}</span>}
      </span>
      <span className="flex min-w-0 flex-col items-start gap-0.5">
        <Link
          to={`/warehouse/documents/${doc.id}`}
          className="break-all text-sm font-medium text-on-primary hover:underline"
        >
          {documentTitle(t, doc)}
        </Link>
        <span className="text-xs text-on-secondary">
          {t(`warehouse:types.${doc.type}`)}
        </span>
        {!completed && <DocumentStatusBadge status={doc.status} />}
      </span>
      <span className="text-sm text-on-secondary">{who}</span>
      {columns.length > 0 && <ModuleCells doc={doc} columns={columns} />}
      {tracksValue && (
        <span
          className={cn(
            "text-sm text-on tabular-nums sm:text-right",
            // A phone row has no column to keep empty.
            !(quotesAmount && doc.total_gross) && "max-sm:hidden",
          )}
        >
          {quotesAmount
            ? formatMoney(doc.total_gross, doc.currency, lang)
            : "—"}
        </span>
      )}
    </li>
  );
}

/**
 * The cells of the modules' columns. The list has no header row, so each
 * value carries its column's name; a row the module has nothing for keeps
 * its empty track at desktop width and takes no line on a phone.
 */
function ModuleCells({
  doc,
  columns,
}: {
  doc: WarehouseDocumentRow;
  columns: FromModule<DocumentColumnContributor>[];
}) {
  const { t } = useTranslation();
  const view = toDocumentView(doc);
  return (
    <>
      {columns.map((column) => {
        const filled = column.hasValue ? column.hasValue(view) : true;
        return (
          <span
            key={`${column.moduleName}:${column.key}`}
            className={cn(
              "flex min-w-0 flex-col gap-0.5",
              !filled && "max-sm:hidden",
            )}
          >
            {filled && (
              <>
                <span className="text-xs text-on-secondary">
                  {t(column.label)}
                </span>
                <span className="break-words text-sm text-on">
                  {column.render(view)}
                </span>
              </>
            )}
          </span>
        );
      })}
    </>
  );
}
