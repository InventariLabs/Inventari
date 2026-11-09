import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Link } from "react-router-dom";
import { useState, useCallback, useMemo, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { downloadBlob } from "@/utils/helpers";
import {
  Download,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  RotateCcw,
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowLeftRight,
  PackagePlus,
  PackageMinus,
  FileCheck,
  TriangleAlert,
} from "lucide-react";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import {
  useDocumentRegister,
  useDocumentRegisterRows,
} from "@/modules/warehouse/hooks/useDocuments";
import { documentsApi } from "@/modules/warehouse/api/documents";
import { DOCUMENT_TYPES } from "@/modules/warehouse/types";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { DateInput } from "@/components/ui/DateInput";
import { Badge } from "@/components/ui/Badge";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { formatMoney, formatDate, todayIso } from "@/utils/formatters";
import type {
  RegisterCurrencyTotal,
  RegisterGroup,
  RegisterDocumentRow,
  RegisterParams,
} from "@/modules/warehouse/types";
import { cn } from "@/lib/utils";
import { TrackingLink } from "@/modules/warehouse/components/shipping/TrackingLink";

type GroupByOption = "type" | "partner" | "location" | "month";

/** Rows fetched per page when a group is expanded. */
const ROWS_PER_PAGE = 50;

const GROUP_BY_OPTIONS: GroupByOption[] = [
  "type",
  "partner",
  "location",
  "month",
];

function getTypeIcon(type: string) {
  switch (type) {
    case "IN":
      return <PackagePlus size={14} className="text-accent-600" />;
    case "OUT":
      return <PackageMinus size={14} className="text-red-500" />;
    case "INT":
      return <ArrowLeftRight size={14} className="text-primary-500" />;
    case "INTERNAL_IN":
      return <ArrowDownToLine size={14} className="text-amber-600" />;
    case "INTERNAL_OUT":
      return <ArrowUpFromLine size={14} className="text-violet-600" />;
    case "CORRECTION":
      return <RotateCcw size={14} className="text-orange-500" />;
    default:
      return <FileCheck size={14} className="text-on-secondary" />;
  }
}

function fmt(
  val: string | null | undefined,
  currency?: string,
  locale?: string,
): string {
  // A value with no currency cannot be written as money: formatMoney would
  // answer a bare "0.00 ?", where 's convention is "—" for a missing
  // figure. Guard both, not just the null value.
  if (val == null || !currency) return "—";
  return formatMoney(val, currency, locale);
}

/** One currency line in a mixed-currency total. */
function CurrencyTotalRow({
  total,
  lang,
}: {
  total: RegisterCurrencyTotal;
  lang: string;
}) {
  return (
    <div className="flex items-center gap-3 font-mono whitespace-nowrap justify-end">
      <span className="text-[10px] font-medium uppercase text-on-muted w-8 text-left">
        {total.currency ?? "—"}
      </span>
      <span className="min-w-[5rem] text-right text-on-secondary tabular-nums">
        {fmt(total.total_net, total.currency ?? undefined, lang)}
      </span>
      <span className="min-w-[4rem] text-right text-on-secondary tabular-nums">
        {fmt(total.total_tax, total.currency ?? undefined, lang)}
      </span>
      <span className="min-w-[6rem] text-right font-semibold text-accent-600 tabular-nums">
        {fmt(total.total_gross, total.currency ?? undefined, lang)}
      </span>
    </div>
  );
}

/** Currency buckets that actually carry a figure. */
function valuedBuckets(
  totals: RegisterCurrencyTotal[] | undefined,
): RegisterCurrencyTotal[] {
  return (totals ?? []).filter(
    (total) =>
      total.total_net != null ||
      total.total_tax != null ||
      total.total_gross != null,
  );
}

/** The one bucket carrying figures, when there is exactly one.
 *
 *  A scope can hold documents with no value at all, and they form a bucket of
 *  their own with nothing in it. The server will not add two buckets together,
 *  so the flat totals come back null — and printing that null put an em dash
 *  where the month's total belongs, on the one screen whose whole job is to
 *  prove the amounts. One valued bucket is one currency, whatever else the
 *  scope contains. */
function soleValuedBucket(
  totals: RegisterCurrencyTotal[] | undefined,
): RegisterCurrencyTotal | null {
  const valued = valuedBuckets(totals);
  return valued.length === 1 ? valued[0] : null;
}

/**
 * The first day of the reader's own month, as a calendar day.
 *
 * `new Date(y, m, 1).toISOString()` renders that local midnight in UTC, so
 * east of Greenwich the window opened on the last day of the previous month.
 */
function firstOfMonth(): string {
  const d = new Date();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  return `${d.getFullYear()}-${month}-01`;
}

interface GroupRowProps {
  group: RegisterGroup;
  /** What the rendered rows are grouped by — read off the response, not the
   * picker, so the label describes the data on screen and not a grouping
   * still in flight. */
  groupBy: string;
  /** The window the group was computed over — rows are paged inside it. */
  window: RegisterParams;
  /** Something in the window was handed to a carrier: rows show carrier
   * and tracking. Left out otherwise, so a register of an organization
   * that never ships carries no two empty columns. */
  shipping: boolean;
}

/**
 * One group as a collapsed card (mobile) — sums in the header, rows paged
 * under them once the reader opens it.
 */
function GroupRow({
  group,
  groupBy,
  window: windowParams,
  shipping,
}: GroupRowProps) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);
  const { t, i18n } = useTranslation("warehouse");
  const { data: profile } = useDocumentProfile();
  // group totals are signed with the currency of the documents
  // they sum — never the organization currency.
  const groupBuckets = valuedBuckets(group.totals_by_currency);
  const multiCurrency = groupBuckets.length > 1;
  const groupSole = soleValuedBucket(group.totals_by_currency);
  const groupCurrency = groupSole?.currency ?? group.currency ?? undefined;
  const groupAmount = (field: "total_net" | "total_tax" | "total_gross") =>
    groupSole ? groupSole[field] : group[field];
  // one type dictionary — profile override → translated short label →
  // raw code. Group labels are raw type codes when grouped by type.
  // A group with no label is the bucket for documents that have nothing to
  // group by; only partner and location can produce one, and each names its
  // own absence.
  // Each key gets its own literal t() call: passing the choice as an argument
  // hides both from the i18n key scanner, which then reports them as orphans.
  const emptyGroupLabel =
    groupBy === "location"
      ? t("register.noLocationGroup")
      : t("register.noPartnerGroup");
  const groupLabel = !group.label
    ? emptyGroupLabel
    : (profile?.type_labels?.[group.label] ??
      t(`typesShort.${group.label}`, { defaultValue: group.label }));

  const {
    data: rowsPage,
    isError: rowsFailed,
    error: rowsError,
    refetch: refetchRows,
  } = useDocumentRegisterRows(
    useMemo(
      () => ({
        date_from: windowParams.date_from,
        date_to: windowParams.date_to,
        group_key: group.key,
        group_by: windowParams.group_by,
        ...(windowParams.type && { type: windowParams.type }),
        status: windowParams.status,
        ...(windowParams.partner_id && { partner_id: windowParams.partner_id }),
        ...(windowParams.location_id && {
          location_id: windowParams.location_id,
        }),
        offset: open ? page * ROWS_PER_PAGE : 0,
        limit: ROWS_PER_PAGE,
      }),
      [open, page, group.key, windowParams],
    ),
    open,
  );
  // Only fetch when open — a closed group needs no rows.
  const rows = open ? (rowsPage?.items ?? []) : [];

  return (
    <div className="rounded-lg border border-border overflow-hidden">
      {/* Group header — stacked on phones: three money columns next
          to the label overflowed 390 px and the gross value was clipped. */}
      <Button
        type="button"
        variant="ghost"
        data-testid={`register-group-${group.key}`}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex flex-col items-start gap-1 px-4 py-3 bg-surface-raised hover:bg-surface-card transition-colors text-left sm:flex-row sm:items-center sm:justify-between sm:gap-3"
      >
        <div className="flex items-center gap-3">
          {open ? (
            <ChevronDown size={16} className="text-on-secondary shrink-0" />
          ) : (
            <ChevronRight size={16} className="text-on-secondary shrink-0" />
          )}
          <span className="font-medium text-on text-sm">{groupLabel}</span>
          <Badge variant="outline" className="text-xs">
            {group.document_count}
          </Badge>
        </div>
        <div className="flex items-center gap-3 text-xs text-on-secondary sm:pr-1 font-mono whitespace-nowrap w-full justify-end sm:w-auto">
          <span className="min-w-[5rem] text-right tabular-nums">
            {fmt(groupAmount("total_net"), groupCurrency, i18n.language)}
          </span>
          <span className="min-w-[4rem] text-right tabular-nums">
            {fmt(groupAmount("total_tax"), groupCurrency, i18n.language)}
          </span>
          <span className="min-w-[6rem] text-right font-medium text-on tabular-nums">
            {fmt(groupAmount("total_gross"), groupCurrency, i18n.language)}
          </span>
        </div>
      </Button>

      {/* Document rows */}
      {open && (
        <div className="divide-y divide-border">
          {rowsFailed ? (
            <div className="px-4 py-3">
              <InlineQueryError
                error={rowsError}
                onRetry={() => void refetchRows()}
              />
            </div>
          ) : (
            rows.length === 0 && (
              <p className="text-xs text-on-secondary px-4 py-3">
                {t("register.noDocuments")}
              </p>
            )
          )}
          {rows.map((doc: RegisterDocumentRow) => (
            <Link
              key={doc.id}
              to={`/warehouse/documents/${doc.id}`}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 hover:bg-surface-raised transition-colors sm:flex-nowrap"
            >
              <span className="shrink-0">{getTypeIcon(doc.type)}</span>
              <span className="font-mono text-xs text-on-secondary sm:w-36 shrink-0 truncate">
                {doc.number}
              </span>
              <span className="text-sm text-on basis-full order-5 truncate min-w-0 sm:order-none sm:basis-auto sm:flex-1">
                {doc.partner_name ||
                  doc.target_location_name ||
                  doc.source_location_name ||
                  "—"}
              </span>
              <span className="text-xs text-on-secondary shrink-0 ml-auto sm:ml-0">
                {formatDate(doc.date)}
              </span>
              {/* Text, not the tracking link: the whole row is already a
                  link to the document, whose card carries the clickable one. */}
              {shipping && doc.carrier && (
                <span className="text-xs text-on-secondary basis-full order-5 truncate">
                  {doc.tracking_number
                    ? `${doc.carrier} · ${doc.tracking_number}`
                    : doc.carrier}
                </span>
              )}
              <div className="flex items-center gap-3 text-xs font-mono shrink-0 whitespace-nowrap basis-full order-6 justify-end sm:order-none sm:basis-auto">
                <span className="min-w-[5rem] text-right text-on-secondary tabular-nums">
                  {fmt(doc.total_net, doc.currency ?? undefined, i18n.language)}
                </span>
                <span className="min-w-[4rem] text-right text-on-secondary tabular-nums">
                  {fmt(doc.total_tax, doc.currency ?? undefined, i18n.language)}
                </span>
                <span className="min-w-[6rem] text-right text-on tabular-nums">
                  {fmt(
                    doc.total_gross,
                    doc.currency ?? undefined,
                    i18n.language,
                  )}
                </span>
              </div>
            </Link>
          ))}

          {rows.length < group.document_count && (
            <div className="flex items-center justify-end gap-2 px-4 py-2 text-xs">
              <Button
                className="min-h-11 md:min-h-0 min-w-11 md:min-w-0"
                type="button"
                variant="outline"
                size="contentSm"
                disabled={page === 0 || rowsPage == null}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                aria-label={t("register.prevPage")}
              >
                <ChevronLeft size={14} />
                {t("register.prevPage")}
              </Button>
              <span className="text-on-secondary tabular-nums">
                {t("register.pageOf", {
                  page: page + 1,
                  total: Math.max(
                    1,
                    Math.ceil(group.document_count / ROWS_PER_PAGE),
                  ),
                })}
              </span>{" "}
              <Button
                className="min-h-11 md:min-h-0 min-w-11 md:min-w-0"
                type="button"
                variant="outline"
                size="contentSm"
                disabled={
                  rowsPage == null ||
                  (page + 1) * ROWS_PER_PAGE >= group.document_count
                }
                onClick={() => setPage((p) => p + 1)}
                aria-label={t("register.nextPage")}
              >
                {t("register.nextPage")}
                <ChevronRight size={14} />
              </Button>
            </div>
          )}

          {/* Group footer / sum row */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 bg-surface-raised/50 text-xs">
            <span className="text-on-secondary font-medium uppercase tracking-wide">
              {t("register.groupSum")}
            </span>
            <span className="text-on-secondary">{group.document_count}</span>
            <div className="ml-auto flex items-center gap-3 font-mono whitespace-nowrap basis-full justify-end sm:basis-auto">
              <span className="min-w-[5rem] text-right text-on-secondary tabular-nums">
                {fmt(groupAmount("total_net"), groupCurrency, i18n.language)}
              </span>
              <span className="min-w-[4rem] text-right text-on-secondary tabular-nums">
                {fmt(groupAmount("total_tax"), groupCurrency, i18n.language)}
              </span>
              <span className="min-w-[6rem] text-right font-semibold text-accent-600 tabular-nums">
                {fmt(groupAmount("total_gross"), groupCurrency, i18n.language)}
              </span>
            </div>
            {multiCurrency && (
              <div className="basis-full flex flex-col gap-1 mt-1">
                {groupBuckets.map((total) => (
                  <CurrencyTotalRow
                    key={total.currency ?? "none"}
                    total={total}
                    lang={i18n.language}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/** The register's money columns, in the one order they are read. */
const MONEY_COL = {
  net: "w-32 text-right tabular-nums",
  tax: "w-28 text-right tabular-nums",
  gross: "w-36 text-right tabular-nums",
};

/**
 * One group as a `<tbody>` of the register table.
 *
 * The register is a list of records with columns — a type, a number, a
 * partner, a date and three amounts — and it was built from `div`s, so the
 * three amounts on the right of every row carried no heading at all: a reader
 * told net from gross by noticing that one is larger. §14.1, and the reason
 * behind it. Grouping is expressed the way a table expresses it, with a
 * `<tbody>` per group rather than a box per group.
 */
/**
 * One group as a `<tbody>` of the register table.
 *
 * The register is a list of records with columns — a type, a number, a
 * partner, a date and three amounts — and it was built from `div`s, so the
 * three amounts on the right of every row carried no heading at all: a reader
 * told net from gross by noticing that one is larger. §14.1, and the reason
 * behind it. Grouping is expressed the way a table expresses it, with a
 * `<tbody>` per group rather than a box per group.
 *
 * The body sits collapsed: the header carries the sums for the
 * whole window, and opening fetches the group's first page of rows with
 * pagination beneath them.
 */
function GroupTableBody({
  group,
  groupBy,
  window: windowParams,
  shipping,
}: GroupRowProps) {
  const { t, i18n } = useTranslation("warehouse");
  const { data: profile } = useDocumentProfile();
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);

  const groupBuckets = valuedBuckets(group.totals_by_currency);
  const multiCurrency = groupBuckets.length > 1;
  const groupSole = soleValuedBucket(group.totals_by_currency);
  const groupCurrency = groupSole?.currency ?? group.currency ?? undefined;
  const groupAmount = (field: "total_net" | "total_tax" | "total_gross") =>
    groupSole ? groupSole[field] : group[field];

  const groupLabel = !group.label
    ? t(
        groupBy === "location"
          ? "register.noLocationGroup"
          : "register.noPartnerGroup",
      )
    : (profile?.type_labels?.[group.label] ??
      t(`typesShort.${group.label}`, { defaultValue: group.label }));

  const {
    data: rowsPage,
    isError: rowsFailed,
    error: rowsError,
    refetch: refetchRows,
  } = useDocumentRegisterRows(
    useMemo(
      () => ({
        date_from: windowParams.date_from,
        date_to: windowParams.date_to,
        group_key: group.key,
        group_by: windowParams.group_by,
        ...(windowParams.type && { type: windowParams.type }),
        status: windowParams.status,
        ...(windowParams.partner_id && { partner_id: windowParams.partner_id }),
        ...(windowParams.location_id && {
          location_id: windowParams.location_id,
        }),
        offset: open ? page * ROWS_PER_PAGE : 0,
        limit: ROWS_PER_PAGE,
      }),
      [open, page, group.key, windowParams],
    ),
    open,
  );
  // A closed group needs no rows; only an open one shows what arrived.
  const rows = open ? (rowsPage?.items ?? []) : [];
  const pageCount = Math.max(
    1,
    Math.ceil(group.document_count / ROWS_PER_PAGE),
  );

  const cell = "px-4 py-2 align-middle border-b border-border";
  // The columns left of the amounts, and the whole row: two more with the
  // carrier and tracking columns.
  const leading = shipping ? 6 : 4;
  const width = leading + 3;

  return (
    <tbody>
      <tr className="bg-surface-raised">
        <th scope="colgroup" colSpan={leading} className="px-4 py-2 text-left">
          {/* eslint-disable-next-line no-restricted-syntax -- a disclosure inside a table heading cell; Button would impose its own height, padding and rounding on a row that has to match the cells beside it */}
          <button
            type="button"
            data-testid={`register-group-${group.key}`}
            onClick={() => setOpen((v) => !v)}
            className="flex items-center gap-3 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-expanded={open}
          >
            {open ? (
              <ChevronDown size={16} className="text-on-secondary shrink-0" />
            ) : (
              <ChevronRight size={16} className="text-on-secondary shrink-0" />
            )}
            <span className="text-sm font-semibold text-on">{groupLabel}</span>
            <Badge variant="outline">{group.document_count}</Badge>
          </button>
        </th>
        <td className={`${MONEY_COL.net} px-4 py-2 text-xs text-on-secondary`}>
          {fmt(groupAmount("total_net"), groupCurrency, i18n.language)}
        </td>
        <td className={`${MONEY_COL.tax} px-4 py-2 text-xs text-on-secondary`}>
          {fmt(groupAmount("total_tax"), groupCurrency, i18n.language)}
        </td>
        <td
          className={`${MONEY_COL.gross} px-4 py-2 text-xs font-medium text-on`}
        >
          {fmt(groupAmount("total_gross"), groupCurrency, i18n.language)}
        </td>
      </tr>

      {open && rowsFailed && (
        <tr>
          <td colSpan={width} className={cell}>
            <InlineQueryError
              error={rowsError}
              onRetry={() => void refetchRows()}
            />
          </td>
        </tr>
      )}

      {open && !rowsFailed && rows.length === 0 && (
        <tr>
          <td colSpan={width} className={`${cell} text-xs text-on-secondary`}>
            {t("register.noDocuments")}
          </td>
        </tr>
      )}

      {open &&
        rows.map((doc: RegisterDocumentRow) => (
          <tr key={doc.id} className="group hover:bg-surface-raised">
            <td className={`${cell} w-10`}>{getTypeIcon(doc.type)}</td>
            <td className={`${cell} font-mono text-xs text-on-secondary`}>
              <Link
                to={`/warehouse/documents/${doc.id}`}
                className="hover:text-accent-700 hover:underline underline-offset-2"
              >
                {doc.number}
              </Link>
            </td>
            <td className={`${cell} text-sm text-on`}>
              {doc.partner_name ||
                doc.target_location_name ||
                doc.source_location_name ||
                "—"}
            </td>
            <td
              className={`${cell} text-xs text-on-secondary whitespace-nowrap`}
            >
              {formatDate(doc.date)}
            </td>
            {shipping && (
              <>
                <td className={`${cell} text-xs text-on-secondary`}>
                  {doc.carrier ?? "—"}
                </td>
                <td className={`${cell} text-xs whitespace-nowrap`}>
                  <TrackingLink
                    trackingNumber={doc.tracking_number}
                    trackingUrl={doc.tracking_url}
                  />
                </td>
              </>
            )}
            <td
              className={`${cell} ${MONEY_COL.net} text-xs text-on-secondary`}
            >
              {fmt(doc.total_net, doc.currency ?? undefined, i18n.language)}
            </td>
            <td
              className={`${cell} ${MONEY_COL.tax} text-xs text-on-secondary`}
            >
              {fmt(doc.total_tax, doc.currency ?? undefined, i18n.language)}
            </td>
            <td className={`${cell} ${MONEY_COL.gross} text-xs text-on`}>
              {fmt(doc.total_gross, doc.currency ?? undefined, i18n.language)}
            </td>
          </tr>
        ))}

      {open && rows.length < group.document_count && (
        <tr>
          <td colSpan={width} className={`${cell} text-xs`}>
            <div className="flex items-center justify-end gap-2">
              {" "}
              <Button
                className="min-h-11 md:min-h-0 min-w-11 md:min-w-0"
                type="button"
                variant="outline"
                size="contentSm"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                aria-label={t("register.prevPage")}
              >
                <ChevronLeft size={14} />
                {t("register.prevPage")}
              </Button>
              <span className="text-on-secondary tabular-nums">
                {t("register.pageOf", { page: page + 1, total: pageCount })}
              </span>{" "}
              <Button
                className="min-h-11 md:min-h-0 min-w-11 md:min-w-0"
                type="button"
                variant="outline"
                size="contentSm"
                disabled={(page + 1) * ROWS_PER_PAGE >= group.document_count}
                onClick={() => setPage((p) => p + 1)}
                aria-label={t("register.nextPage")}
              >
                {t("register.nextPage")}
                <ChevronRight size={14} />
              </Button>
            </div>
          </td>
        </tr>
      )}

      {open && (
        <tr className="bg-surface-raised/50">
          <td colSpan={leading} className={`${cell} text-xs text-on-secondary`}>
            {t("register.groupSum")} · {group.document_count}
          </td>
          <td className={`${cell} ${MONEY_COL.net} text-xs text-on-secondary`}>
            {fmt(groupAmount("total_net"), groupCurrency, i18n.language)}
          </td>
          <td className={`${cell} ${MONEY_COL.tax} text-xs text-on-secondary`}>
            {fmt(groupAmount("total_tax"), groupCurrency, i18n.language)}
          </td>
          <td
            className={`${cell} ${MONEY_COL.gross} text-xs font-medium text-accent-600`}
          >
            {fmt(groupAmount("total_gross"), groupCurrency, i18n.language)}
          </td>
        </tr>
      )}

      {open &&
        multiCurrency &&
        groupBuckets.map((total) => (
          <tr key={total.currency ?? "none"} className="bg-surface-raised/50">
            <td
              colSpan={leading}
              className={`${cell} text-[10px] text-on-muted`}
            >
              {total.currency ?? "—"}
            </td>
            <td
              className={`${cell} ${MONEY_COL.net} text-xs text-on-secondary`}
            >
              {fmt(total.total_net, total.currency ?? undefined, i18n.language)}
            </td>
            <td
              className={`${cell} ${MONEY_COL.tax} text-xs text-on-secondary`}
            >
              {fmt(total.total_tax, total.currency ?? undefined, i18n.language)}
            </td>
            <td
              className={`${cell} ${MONEY_COL.gross} text-xs font-medium text-accent-600`}
            >
              {fmt(
                total.total_gross,
                total.currency ?? undefined,
                i18n.language,
              )}
            </td>
          </tr>
        ))}
    </tbody>
  );
}

/**
 * What the totals above fold in or leave out, said where they are read: a
 * write-off is in them at what it cost, and a document posted without a
 * price is in them for nothing.
 */
function TotalsNotes({
  summary,
}: {
  summary: { scrap_documents: number; documents_without_value: number };
}) {
  const { t } = useTranslation("warehouse");
  if (summary.scrap_documents === 0 && summary.documents_without_value === 0)
    return null;
  return (
    <div className="space-y-1 text-xs text-on-secondary">
      {summary.scrap_documents > 0 && (
        <p>{t("register.includesScrap", { total: summary.scrap_documents })}</p>
      )}
      {summary.documents_without_value > 0 && (
        <p
          role="status"
          className="flex items-start gap-2 text-amber-800 dark:text-amber-300"
        >
          <TriangleAlert size={14} className="mt-0.5 shrink-0" />
          <span>
            {t("register.documentsWithoutValue", {
              total: summary.documents_without_value,
            })}
          </span>
        </p>
      )}
    </div>
  );
}

export default function DocumentRegisterPage() {
  const { t, i18n } = useTranslation("warehouse");
  const isDesktop = useMediaQuery("(min-width: 1024px)");
  const lang = i18n.language?.substring(0, 2) ?? "en";

  const [dateFrom, setDateFrom] = useState(() => firstOfMonth());
  const [dateTo, setDateTo] = useState(() => todayIso());
  const [typeFilter, setTypeFilter] = useState<string>("ALL");
  const [groupBy, setGroupBy] = useState<GroupByOption>("type");

  const { setHeader } = useModulePageHeader();

  // The register is reached from History's office panel; the module bar no
  // longer names it, so the screen brings its own title.
  useEffect(() => {
    setHeader({
      title: t("register.title"),
      subtitle: t("register.subtitle"),
    });
  }, [setHeader, t]);

  const { data: profile } = useDocumentProfile();

  const params: RegisterParams = useMemo(
    () => ({
      date_from: dateFrom,
      date_to: dateTo,
      ...(typeFilter !== "ALL" && { type: typeFilter }),
      status: "COMPLETED",
      group_by: groupBy,
    }),
    [dateFrom, dateTo, typeFilter, groupBy],
  );

  const { data, isLoading, isError } = useDocumentRegister(params);
  const shipping = Boolean(data?.summary.has_shipments);
  const summarySole = soleValuedBucket(data?.summary.totals_by_currency);
  // the summary is signed by the currency of the documents it sums.
  const summaryCurrency =
    summarySole?.currency ?? data?.summary.currency ?? undefined;

  /** Flat total, or a stacked per-currency list for mixed-currency data.
   *  Documents with no value form a bucket with a null currency and no
   *  amounts; printed as a line of its own it was a lone em dash hanging
   *  over every figure. A bucket that sums to nothing is not a line. */
  const renderTotal = (
    flat: string | null,
    field: "total_net" | "total_tax" | "total_gross",
  ) => {
    const buckets = valuedBuckets(data?.summary.totals_by_currency);
    if (buckets.length > 1) {
      return (
        <span className="flex flex-col gap-1 text-sm">
          {buckets.map((ct) => (
            <span key={ct.currency ?? "none"}>
              {fmt(ct[field], ct.currency ?? undefined, lang)}
            </span>
          ))}
        </span>
      );
    }
    // A register over no documents totals zero — it is not an unknown. The
    // em dash beside a "0" document count read as two answers to the same
    // question. Without a currency the zero has nothing to be denominated
    // in, so `fmt` falls back to the em dash instead of a "0.00 ?" marker.
    return fmt(
      summarySole ? summarySole[field] : (flat ?? "0"),
      summaryCurrency,
      lang,
    );
  };

  const handleCsvExport = useCallback(async () => {
    try {
      const blob = await documentsApi.getRegisterCsv({
        ...params,
        output_format: "csv",
      });
      downloadBlob(blob, `register_${dateFrom}_${dateTo}.csv`);
    } catch (err) {
      // "The user will notice the download didn't happen" is exactly what they
      // will not notice — a browser gives no sign either way.
      toast.error(extractApiError(err, t("register.exportFailed")));
    }
  }, [params, dateFrom, dateTo, t]);
  const typeOptions = ["ALL", ...DOCUMENT_TYPES] as const;

  return (
    <div className="space-y-5">
      {/* Filters bar */}
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-3">
          {/* Date range */}
          <div className="flex items-center gap-2">
            <DateInput
              label={t("register.dateFrom")}
              value={dateFrom}
              onChange={(e) => setDateFrom(e)}
              wrapperClassName="w-36"
              className="text-sm"
            />
            <span className="text-on-secondary mt-5">–</span>
            <DateInput
              label={t("register.dateTo")}
              value={dateTo}
              onChange={(e) => setDateTo(e)}
              wrapperClassName="w-36"
              className="text-sm"
            />
          </div>

          {/* Type chips */}
          <div>
            <p className="block text-xs text-on-secondary mb-1">
              {t("register.docType")}
            </p>
            <div className="flex flex-wrap gap-1">
              {typeOptions.map((t_opt) => (
                <Button
                  key={t_opt}
                  type="button"
                  variant={typeFilter === t_opt ? "default" : "outline"}
                  size="sm"
                  onClick={() => setTypeFilter(t_opt)}
                  className={cn(
                    "px-2.5 rounded-md font-medium transition-colors",
                    typeFilter === t_opt && "border border-primary-600",
                  )}
                >
                  {t_opt === "ALL"
                    ? t("register.all")
                    : (profile?.type_labels?.[t_opt] ??
                      t(`typesShort.${t_opt}`))}
                </Button>
              ))}
            </div>
          </div>

          {/* Group by */}
          <div>
            <p className="block text-xs text-on-secondary mb-1">
              {t("register.groupBy")}
            </p>
            <div className="flex gap-1">
              {GROUP_BY_OPTIONS.map((opt) => (
                <Button
                  key={opt}
                  type="button"
                  variant={groupBy === opt ? "default" : "outline"}
                  size="sm"
                  onClick={() => setGroupBy(opt)}
                  className={cn(
                    "px-2.5 rounded-md font-medium transition-colors",
                    groupBy === opt && "border border-primary-600",
                  )}
                >
                  {t(`register.groupBy_${opt}`)}
                </Button>
              ))}
            </div>
          </div>

          <div className="ml-auto">
            <Button
              variant="outline"
              size="sm"
              leftIcon={<Download size={14} />}
              onClick={handleCsvExport}
              disabled={!data || data.summary.total_documents === 0}
            >
              {t("register.exportCsv")}
            </Button>
          </div>
        </div>
      </Card>

      {/* Summary cards.
          One size across the row. The odd one out was 24px on "54" while the
          three money tiles beside it sat at 20px — a fit for the short string,
          not a rank, and it read as one tile shouting over its neighbours.
          `tabular-nums` is the part that does the visible work: without fixed
          digit widths the four amounts do not line up under each other. */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Card className="p-4 text-center">
            <p className="text-xs text-on-secondary mb-1">
              {t("register.totalDocuments")}
            </p>
            <p className="text-xl font-semibold text-on tabular-nums">
              {data.summary.total_documents}
            </p>
          </Card>
          <Card className="p-4 text-center">
            {/* A write-off is in this sum at what it cost (it is a document of
                the window with a value, and the sum has to equal the rows
                under it), so the label says so rather than leave "Net" to be
                read as receipts less what went out. */}
            <p className="text-xs text-on-secondary mb-1">
              {data.summary.scrap_documents > 0
                ? t("register.totalNetWithScrap")
                : t("register.totalNet")}
            </p>
            <p className="text-xl font-semibold text-on tabular-nums">
              {renderTotal(data.summary.total_net, "total_net")}
            </p>
          </Card>
          <Card className="p-4 text-center">
            <p className="text-xs text-on-secondary mb-1">
              {t("register.totalTax")}
            </p>
            <p className="text-xl font-semibold text-on tabular-nums">
              {renderTotal(data.summary.total_tax, "total_tax")}
            </p>
          </Card>
          <Card className="p-4 text-center">
            <p className="text-xs text-on-secondary mb-1">
              {t("register.totalGross")}
            </p>
            <p className="text-xl font-semibold text-accent-600 tabular-nums">
              {renderTotal(data.summary.total_gross, "total_gross")}
            </p>
          </Card>
        </div>
      )}

      {data && <TotalsNotes summary={data.summary} />}

      {/* Groups */}
      {isLoading && (
        <p className="text-sm text-on-secondary text-center py-8">
          {t("register.loading")}
        </p>
      )}
      {isError && (
        <p className="text-sm text-red-500 text-center py-8">
          {t("register.error")}
        </p>
      )}
      {data && data.groups.length === 0 && (
        <Card className="p-8 text-center space-y-3">
          <p className="text-on-secondary text-sm">{t("register.empty")}</p>
          {/* A ledger of nothing left the reader on a dead end: no way to the
              documents it would have listed. */}
          <Link
            to="/warehouse/history"
            className="text-sm font-medium text-on-primary hover:underline"
          >
            {t("register.emptyGoToDocuments")}
          </Link>
        </Card>
      )}
      {data && data.groups.length > 0 && (
        <>
          {/* One branch in the DOM, not two. `hidden lg:block` would leave
              both here — doubling a register that can run to hundreds of rows
              and making a screen reader walk it twice. The desktop branch is
              a table with a heading per column and a `<tbody>` per group;
              below `lg` the three money columns next to a label overflow
              390px, so §14.1 keeps the stacked branch as it is. */}
          {isDesktop ? (
            <div className="rounded-lg border border-border overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="text-xs font-medium uppercase tracking-wider text-on-muted bg-surface">
                    <th scope="col" className="px-4 py-2 text-left" colSpan={2}>
                      {t("register.colDocument")}
                    </th>
                    <th scope="col" className="px-4 py-2 text-left">
                      {t("register.colPartner")}
                    </th>
                    <th scope="col" className="px-4 py-2 text-left">
                      {t("register.colDate")}
                    </th>
                    {shipping && (
                      <>
                        <th scope="col" className="px-4 py-2 text-left">
                          {t("shipping.carrier")}
                        </th>
                        <th scope="col" className="px-4 py-2 text-left">
                          {t("register.colTracking")}
                        </th>
                      </>
                    )}
                    <th scope="col" className={`px-4 py-2 ${MONEY_COL.net}`}>
                      {t("register.totalNet")}
                    </th>
                    <th scope="col" className={`px-4 py-2 ${MONEY_COL.tax}`}>
                      {t("register.totalTax")}
                    </th>
                    <th scope="col" className={`px-4 py-2 ${MONEY_COL.gross}`}>
                      {t("register.totalGross")}
                    </th>
                  </tr>
                </thead>
                {data.groups.map((group: RegisterGroup) => (
                  <GroupTableBody
                    key={group.key}
                    group={group}
                    groupBy={data.group_by}
                    window={params}
                    shipping={shipping}
                  />
                ))}
              </table>
            </div>
          ) : (
            <div className="space-y-2">
              {data.groups.map((group: RegisterGroup) => (
                <GroupRow
                  key={group.key}
                  group={group}
                  groupBy={data.group_by}
                  window={params}
                  shipping={shipping}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
