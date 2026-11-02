import { Fragment } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { Textarea } from "@/components/ui/Textarea";
import type { PartnerOption } from "@/hooks/usePartnerPicker";
import type { StorageLocationSummary } from "@/types";
import type { WarehouseDocument } from "@/modules/warehouse/types";
import {
  documentApprover,
  documentConfirmation,
} from "@/modules/warehouse/components/documentConfirmation";

interface DocumentMetadataGridProps {
  doc: WarehouseDocument;
  isDraft: boolean;
  partners: PartnerOption[];
  onPartnerSearch?: (query: string) => void;
  partnersLoading?: boolean;
  storages: StorageLocationSummary[];
  notesEditValue: string | null;
  onNotesChange: (v: string) => void;
  onNotesBlur: (v: string) => void;
  onPartnerChange: (partnerId: string) => void;
  /** Calendar days — `scheduled_date` is a DATE column, not an instant. */
  formatDate: (dateStr: string | null) => string;
  /** Instants — created, confirmed and completed stamps carry a time. */
  formatDateTime: (dateStr: string | null) => string;
  t: (key: string, options?: Record<string, unknown>) => string;
}

/** One moment in the document's workflow: when it happened and by whose
 * hand. Confirmed, approved, completed and cancelled are the same cell twice
 * over — a stamp and an actor — so they are one list rather than eight copies
 * of the same JSX; the next workflow moment becomes one entry here.
 *
 * `approved` is the approval's own moment: the confirmation keeps its author
 * through the approval, so the hand that approved the document needs a place
 * of its own rather than overwriting the confirmer's.
 */
function workflowMoments(
  doc: WarehouseDocument,
  t: (key: string, options?: Record<string, unknown>) => string,
): {
  stampLabel: string;
  actorLabel: string;
  at: string | null | undefined;
  by: string | null | undefined;
  byName: string | null | undefined;
}[] {
  const confirmation = documentConfirmation(doc);
  const approver = documentApprover(doc);
  return [
    {
      stampLabel: t("warehouse:fields.confirmedAt"),
      actorLabel: t("warehouse:fields.confirmedBy"),
      at: confirmation?.at,
      by: confirmation?.by,
      byName: confirmation?.byName,
    },
    {
      stampLabel: t("warehouse:fields.approvedAt"),
      actorLabel: t("warehouse:fields.approvedBy"),
      at: approver?.at,
      by: approver?.by,
      byName: approver?.byName,
    },
    {
      stampLabel: t("warehouse:fields.completedAt"),
      actorLabel: t("warehouse:fields.completedBy"),
      at: doc.completed_at,
      by: doc.completed_by,
      byName: doc.completed_by_name,
    },
    {
      stampLabel: t("warehouse:fields.cancelledAt"),
      actorLabel: t("warehouse:fields.cancelledBy"),
      at: doc.cancelled_at,
      by: doc.cancelled_by,
      byName: doc.cancelled_by_name,
    },
  ];
}

/** A draft with no partner yet gets the picker in place of the name. */
/** Once the document is done the day is its own date, the one the register
 * files it under — "scheduled" would read as a plan nobody kept. */
function dateLabel(
  status: string,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  return status === "COMPLETED"
    ? t("warehouse:fields.documentDate")
    : t("warehouse:fields.scheduledDate");
}

function offersPartnerPicker(doc: WarehouseDocument, isDraft: boolean) {
  return (
    isDraft &&
    !doc.partner_id &&
    !doc.partner_snapshot &&
    doc.type !== "CORRECTION"
  );
}

/** Who wrote the document down, falling back to the id for a record that
 * carries no name (the account was deleted, or predates the name lookup). */
function creatorName(doc: WarehouseDocument): string {
  return doc.created_by_name ?? doc.created_by;
}

/** The document a return reverses, linked under a translated label.
 *
 * This row is the return's pointer to its original: the server stores no
 * note sentence (one row has no language every later reader shares) and
 * exposes the ``returns`` relation beside the document instead. Kept out of
 * the grid's own body so the frozen function baseline does not grow. */
function ReturnOfReference({
  doc,
  t,
}: {
  doc: WarehouseDocument;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  if (!doc.return_of_id) return null;
  return (
    <div>
      <p className="text-xs text-on-muted mb-0.5">
        {t("warehouse:returns.isReturnOf")}
      </p>
      <Link
        to={`/warehouse/documents/${doc.return_of_id}`}
        className="inline-flex items-center gap-1 text-sm text-on-primary hover:underline"
      >
        {doc.return_of_number ?? doc.return_of_id}
        <ArrowUpRight size={13} />
      </Link>
    </div>
  );
}

/** The correction that undid this document in one press, linked under a
 * translated label. Only a completed reversal is attached by the server, so
 * the row never claims stock went back that is still waiting for approval. */
function ReversedByReference({
  doc,
  t,
}: {
  doc: WarehouseDocument;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  if (!doc.reversed_by_id) return null;
  return (
    <div>
      <p className="text-xs text-on-muted mb-0.5">
        {t("warehouse:fields.reversedBy")}
      </p>
      <Link
        to={`/warehouse/documents/${doc.reversed_by_id}`}
        className="inline-flex items-center gap-1 text-sm text-on-primary hover:underline"
      >
        {doc.reversed_by_number ?? doc.reversed_by_id}
        <ArrowUpRight size={13} />
      </Link>
    </div>
  );
}

export function DocumentMetadataGrid({
  doc,
  isDraft,
  partners,
  onPartnerSearch,
  partnersLoading,
  storages,
  notesEditValue,
  onNotesChange,
  onNotesBlur,
  onPartnerChange,
  formatDate,
  formatDateTime,
  t,
}: DocumentMetadataGridProps) {
  const partnerName =
    (doc.partner_snapshot?.name as string | undefined) ??
    partners.find((p) => p.id === doc.partner_id)?.name;
  const pickingPartner = offersPartnerPicker(doc, isDraft);
  const sourceLocation = storages.find(
    (s: StorageLocationSummary) => s.id === doc.source_location_id,
  )?.name;
  const targetLocation = storages.find(
    (s: StorageLocationSummary) => s.id === doc.target_location_id,
  )?.name;

  // The form refused to save without a reason; a card that never showed it
  // asked the question and then hid the answer. Corrections name their
  // dictionary, returns theirs — the two code sets are disjoint but "Other".
  // The split reads doc.type, so a fourth document type that started writing
  // reason_code would read the return dictionary; reason_code is written by
  // exactly three paths today, and this note is the tripwire.
  const reason = (() => {
    if (!doc.reason_code) return null;
    const ns =
      doc.type === "CORRECTION"
        ? "correction"
        : doc.type === "SCRAP"
          ? "scrap"
          : "return";
    return {
      label: t(`warehouse:reasons.${ns}.label`),
      value: t(`warehouse:reasons.${ns}.codes.${doc.reason_code}`),
    };
  })();

  return (
    <>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-2 border-t border-border text-sm">
        <div>
          <p className="text-xs text-on-muted mb-0.5">
            {t("warehouse:fields.createdAt")}
          </p>
          <p className="text-on">{formatDateTime(doc.created_at)}</p>
        </div>
        {/* Who wrote the document down. The record carries the name and the
            page showed only the date, so three months later nobody could say
            whose document it was. */}
        <div>
          <p className="text-xs text-on-muted mb-0.5">
            {t("warehouse:fields.createdBy")}
          </p>
          <p className="text-on text-sm">{creatorName(doc)}</p>
        </div>
        {doc.scheduled_date && (
          <div>
            <p className="text-xs text-on-muted mb-0.5">
              {dateLabel(doc.status, t)}
            </p>
            {/* A day, not an instant: `scheduled_date` printed through the
                timestamp formatter read "01/01/2026, 12:00 AM" — midnight,
                an hour nobody schedules. */}
            <p className="text-on">{formatDate(doc.scheduled_date)}</p>
          </div>
        )}
        {(partnerName || (isDraft && doc.type !== "CORRECTION")) && (
          // The picker takes the row below `sm:`; squeezed into half of a
          // phone grid its placeholder had no room to read.
          <div
            className={pickingPartner ? "col-span-2 sm:col-span-1" : undefined}
          >
            {pickingPartner ? (
              <SearchableCombobox
                label={t("warehouse:fields.partner")}
                options={partners}
                onSearchChange={onPartnerSearch}
                loading={partnersLoading}
                value={doc.partner_id ?? ""}
                onChange={onPartnerChange}
                placeholder={t("warehouse:form.selectPartner")}
                searchPlaceholder={t("warehouse:form.searchPartner")}
                emptyMessage={t("warehouse:form.noPartnersFound")}
                title={t("warehouse:fields.partner") as string}
              />
            ) : (
              <>
                <p className="text-xs text-on-muted mb-0.5">
                  {t("warehouse:fields.partner")}
                </p>
                <p className="text-on">{partnerName}</p>
              </>
            )}
          </div>
        )}
        {sourceLocation && (
          <div>
            <p className="text-xs text-on-muted mb-0.5">
              {t("warehouse:fields.sourceLocation")}
            </p>
            <p className="text-on">{sourceLocation}</p>
          </div>
        )}
        {targetLocation && (
          <div>
            <p className="text-xs text-on-muted mb-0.5">
              {t("warehouse:fields.targetLocation")}
            </p>
            <p className="text-on">{targetLocation}</p>
          </div>
        )}
        {workflowMoments(doc, t).map((moment) => (
          <Fragment key={moment.stampLabel}>
            {moment.at && (
              <div>
                <p className="text-xs text-on-muted mb-0.5">
                  {moment.stampLabel}
                </p>
                <p className="text-on">{formatDateTime(moment.at)}</p>
              </div>
            )}
            {moment.by && (
              <div>
                <p className="text-xs text-on-muted mb-0.5">
                  {moment.actorLabel}
                </p>
                <p className="text-on text-sm">{moment.byName ?? moment.by}</p>
              </div>
            )}
          </Fragment>
        ))}
        {doc.type === "CORRECTION" && doc.corrects_document_id && (
          <div>
            <p className="text-xs text-on-muted mb-0.5">
              {t("warehouse:fields.externalReference")}
            </p>
            <Link
              to={`/warehouse/documents/${doc.corrects_document_id}`}
              className="inline-flex items-center gap-1 text-sm text-on-primary hover:underline"
            >
              {doc.external_reference ?? doc.corrects_document_id}
              <ArrowUpRight size={13} />
            </Link>
          </div>
        )}
        {doc.type !== "CORRECTION" && doc.external_reference && (
          <div>
            <p className="text-xs text-on-muted mb-0.5">
              {t("warehouse:fields.externalReference")}
            </p>
            <p className="text-on">{doc.external_reference}</p>
          </div>
        )}
        {doc.backorder_id && (
          <div>
            <p className="text-xs text-on-muted mb-0.5">
              {t("warehouse:backorder.isBackorderOf")}
            </p>
            <Link
              to={`/warehouse/documents/${doc.backorder_id}`}
              className="inline-flex items-center gap-1 text-sm text-on-primary hover:underline"
            >
              {t("warehouse:backorder.viewOriginal")}
              <ArrowUpRight size={13} />
            </Link>
          </div>
        )}
        {doc.generated_backorder_id && (
          <div>
            <p className="text-xs text-on-muted mb-0.5">
              {t("warehouse:backorder.createdBanner", {
                number: doc.generated_backorder_number ?? "",
              })}
            </p>
            <Link
              to={`/warehouse/documents/${doc.generated_backorder_id}`}
              className="inline-flex items-center gap-1 text-sm text-on-primary hover:underline"
            >
              {t("warehouse:backorder.viewBackorder")}
              <ArrowUpRight size={13} />
            </Link>
          </div>
        )}
        <ReturnOfReference doc={doc} t={t} />
        <ReversedByReference doc={doc} t={t} />
        {reason && (
          <div>
            <p className="text-xs text-on-muted mb-0.5">{reason.label}</p>
            <p className="text-on">{reason.value}</p>
          </div>
        )}
      </div>

      {(doc.notes || (isDraft && doc.type === "CORRECTION")) && (
        <div className="pt-2 border-t border-border">
          <p className="text-xs text-on-muted mb-0.5">
            {t("warehouse:fields.notes")}
          </p>
          {isDraft && doc.type === "CORRECTION" ? (
            <Textarea
              aria-label={t("warehouse:fields.notes")}
              className="w-full text-sm text-on bg-surface border border-border rounded-md p-2 resize-none focus:outline-none focus:border-primary-500 transition-colors"
              rows={3}
              value={notesEditValue ?? doc.notes ?? ""}
              placeholder={t("warehouse:form.notesPlaceholder")}
              onChange={(e) => onNotesChange(e.target.value)}
              onBlur={() => onNotesBlur(notesEditValue ?? "")}
            />
          ) : (
            <p className="text-sm text-on">{doc.notes}</p>
          )}
        </div>
      )}
    </>
  );
}
