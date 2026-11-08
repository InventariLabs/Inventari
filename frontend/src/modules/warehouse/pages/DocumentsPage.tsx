import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { FileSpreadsheet, SearchX, X } from "lucide-react";
import { toast } from "sonner";
import { documentTitle } from "@/modules/warehouse/lib/documentTitle";
import { extractApiError } from "@/lib/errors";
import { Button } from "@/components/ui/Button";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import { QueryError } from "@/components/ui/QueryResult";
import { PartnerFilterBanner } from "@/modules/partners/moduleApi";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Pagination } from "@/module-sdk";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { BulkActionBar } from "@/modules/warehouse/components/BulkActionBar";
import { DocumentListItem } from "@/modules/warehouse/components/DocumentListItem";
import { DocumentsGettingStarted } from "@/modules/warehouse/components/DocumentsGettingStarted";
import { DocumentsFilters } from "@/modules/warehouse/components/DocumentsFilters";
import { ListPickingSheet } from "@/modules/warehouse/components/picking/ListPickingSheet";
import { NewDocumentMenu } from "@/modules/warehouse/components/NewDocumentMenu";
import { useDocumentBulkActions } from "@/modules/warehouse/hooks/useDocumentBulkActions";
import { useDocumentsList } from "@/modules/warehouse/hooks/useDocumentsList";
import {
  useDocument,
  useDocumentWorkflow,
  useDuplicateDocument,
} from "@/modules/warehouse/hooks/useDocuments";
import DocumentFormModal from "@/modules/warehouse/components/DocumentFormModal";
import OpeningStockImportModal from "@/modules/warehouse/components/OpeningStockImportModal";
import type {
  DocumentType,
  WarehouseDocumentRow,
} from "@/modules/warehouse/types";
import { formatDate } from "@/utils/formatters";

export default function DocumentsPage() {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("warehouse");
  const [newDocType, setNewDocType] = useState<DocumentType | null>(null);
  // A list row carries no lines; the form edits the whole document, read
  // from its own endpoint when the row asks for it.
  const [editingId, setEditingId] = useState<string | null>(null);
  const editing = useDocument(editingId ?? undefined);
  const editingDocument = editing.data;
  const editFailed = editingId !== null && editing.isError;
  useEffect(() => {
    if (!editFailed) return;
    toast.error(extractApiError(editing.error, t("errors.loadDocumentFailed")));
    setEditingId(null);
  }, [editFailed, editing.error, t]);
  const [confirmAction, setConfirmAction] = useState<{
    type: "confirm" | "cancel" | "delete";
    doc: WarehouseDocumentRow;
  } | null>(null);

  const list = useDocumentsList();
  const {
    documents,
    isLoading,
    skip,
    limit,
    total,
    isNarrowed,
    clearFilters,
    onPrev,
    onNext,
    onPageChange,
    onLimitChange,
    isError,
    refetch,
    partnerId,
    clearPartnerFilter,
  } = list;

  // Fifteen controls for narrowing a list with nothing in it, sitting above
  // the three steps that explain how to put something in it. They return with
  // the first document, and whenever the reader has narrowed the list and
  // needs a way to widen it again.
  const showFilters = isLoading || total > 0 || isNarrowed;

  const { confirmDocument, cancelDocument, deleteDocument } =
    useDocumentWorkflow();
  const duplicateDocument = useDuplicateDocument();

  // duplicate straight from the list into a fresh draft.
  const handleDuplicate = async (doc: WarehouseDocumentRow) => {
    try {
      const dup = await duplicateDocument.mutateAsync(doc.id);
      toast.success(
        t("actions.duplicateSuccess", { number: documentTitle(t, dup) }),
      );
      navigate(`/warehouse/documents/${dup.id}`);
    } catch (error: unknown) {
      // A 403 is not a malfunction. Replacing the server's sentence with our
      // own "failed to duplicate" left the reader unable to tell "you may
      // not" from "it broke", so they either asked an administrator to fix
      // something that works or kept retrying. `extractApiError` already
      // draws the line: a 4xx detail is a translated sentence, a 5xx is not.
      toast.error(extractApiError(error, t("actions.duplicateError")));
    }
  };

  const handleAction = () => {
    if (!confirmAction) return;
    const { type, doc } = confirmAction;

    const mutationMap = {
      confirm: confirmDocument,
      cancel: cancelDocument,
      delete: deleteDocument,
    };

    const toastMap = {
      confirm: {
        success: t("toast.confirmed"),
        error: t("errors.confirmFailed"),
      },
      cancel: {
        success: t("toast.cancelled"),
        error: t("errors.cancelFailed"),
      },
      delete: { success: t("toast.deleted"), error: t("errors.deleteFailed") },
    };

    mutationMap[type].mutate(doc.id, {
      onSuccess: () => {
        toast.success(toastMap[type].success);
        setConfirmAction(null);
      },
      onError: (err) => {
        toast.error(extractApiError(err, toastMap[type].error));
        setConfirmAction(null);
      },
    });
  };

  const bulk = useDocumentBulkActions(documents, {
    confirmMutation: confirmDocument,
    deleteMutation: deleteDocument,
  });

  const [showOpeningStock, setShowOpeningStock] = useState(false);
  const [pickingIds, setPickingIds] = useState<string[] | null>(null);
  const headerActions = useMemo(
    () =>
      !canWrite ? undefined : (
        <div className="flex gap-2 shrink-0 ml-auto">
          {/* The day a company leaves its spreadsheet: one receipt out of
            the whole sheet, instead of one line typed at a time. */}
          <Button
            size="sm"
            variant="outline"
            leftIcon={<FileSpreadsheet size={16} />}
            onClick={() => setShowOpeningStock(true)}
          >
            {t("openingStock.button")}
          </Button>
          {/* a single unambiguous "+ New document" menu on every
            width. The old desktop row of six type buttons sat right above
            the type filter tabs with nearly identical labels — creating
            and filtering were visually indistinguishable. */}
          <NewDocumentMenu onSelect={setNewDocType} />
        </div>
      ),
    [canWrite, t],
  );

  useEffect(() => {
    setHeader({ actions: headerActions });
  }, [setHeader, headerActions]);

  return (
    // tighter mobile rhythm — the 24px gaps between header, filters
    // and list were a full row of the phone's first screen.
    <div className="space-y-3 md:space-y-6">
      <ReadOnlyNotice module="warehouse" />
      {showFilters && (
        <DocumentsFilters {...list} scannerEnabled={!pickingIds} t={t} />
      )}

      {/* Reached from a partner card, filtered to that partner. */}
      <PartnerFilterBanner
        partnerId={partnerId}
        label={(name) => t("filters.partnerFilter", { name })}
        onClear={clearPartnerFilter}
      />

      {/* Document List */}
      {isLoading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
        </div>
      ) : isError ? (
        <QueryError
          message={t("errors.loadDocumentsFailed")}
          onRetry={() => void refetch()}
        />
      ) : documents.length === 0 && !isNarrowed ? (
        <DocumentsGettingStarted onCreateFirst={() => setNewDocType("IN")} />
      ) : documents.length === 0 ? (
        // The two empties of a filtered list are different answers. This one
        // used to give the other's: "No documents yet. Create your first
        // warehouse document" over a shelf of forty-nine, telling the reader
        // their search was a missing database and prescribing a cure a
        // read-only account is not allowed to take.
        <EmptyState
          icon={SearchX}
          title={t("empty.noResultsTitle")}
          description={t("empty.noResultsSubtitle")}
          primaryAction={
            <EmptyStateAction
              label={t("empty.clearFilters")}
              onClick={clearFilters}
              leftIcon={X}
            />
          }
        />
      ) : (
        <div className="space-y-2">
          {/* One mechanism, not two: the row checkboxes are always there and
              "Select all" acts on them. The old "Select" button toggled a mode
              whose only job was to unhide those checkboxes, while select-all
              worked with the mode off — two controls of nearly the same name
              for one job. */}
          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-xs text-on-secondary cursor-pointer select-none">
              <input
                type="checkbox"
                checked={
                  documents.length > 0 &&
                  bulk.selectedIds.size === documents.length
                }
                onChange={bulk.toggleSelectAll}
                aria-label={t("bulk.selectAll")}
                className="h-4 w-4 rounded border-border text-primary-600 focus:ring-primary-500"
              />
              {t("bulk.selectAll")}
            </label>
          </div>
          <BulkActionBar
            {...bulk.barProps}
            onPick={setPickingIds}
            canWrite={canWrite}
            t={t}
          />
          {documents.map((doc) => (
            <DocumentListItem
              key={doc.id}
              doc={doc}
              columns={list.moduleColumns}
              // The day the register files it under, which is also what the list
              // sorts and filters by — not the day it was typed in.
              formattedDate={formatDate(doc.scheduled_date ?? doc.created_at)}
              onOpenDetails={(id) => navigate(`/warehouse/documents/${id}`)}
              onEdit={(doc) => setEditingId(doc.id)}
              onRequestAction={(type, selectedDoc) =>
                setConfirmAction({ type, doc: selectedDoc })
              }
              onDuplicate={canWrite ? handleDuplicate : undefined}
              // The sheet opens over this document alone; the server answers
              // with the session already open over it, however many
              // dispatches that session covers.
              onResumePicking={(documentId) => setPickingIds([documentId])}
              isDuplicatePending={duplicateDocument.isPending}
              canWrite={canWrite}
              isSelected={bulk.selectedIds.has(doc.id)}
              selectionActive={bulk.selectedIds.size > 0}
              onToggleSelect={bulk.toggleSelect}
            />
          ))}
        </div>
      )}

      {/* Jump-to-page and rows-per-page were already in the shared pager;
          this list was the one that passed neither. */}
      <Pagination
        skip={skip}
        limit={limit}
        total={total}
        onPrev={onPrev}
        onNext={onNext}
        onPageChange={onPageChange}
        onLimitChange={onLimitChange}
      />

      {/* Modals */}
      {newDocType && (
        <DocumentFormModal
          initialType={newDocType}
          onClose={() => setNewDocType(null)}
          onCreated={({ id }) => navigate(`/warehouse/documents/${id}`)}
        />
      )}
      {editingId && editingDocument?.id === editingId && (
        <DocumentFormModal
          document={editingDocument}
          onClose={() => setEditingId(null)}
        />
      )}
      {showOpeningStock && (
        <OpeningStockImportModal onClose={() => setShowOpeningStock(false)} />
      )}

      {/* The dispatches a session is open over, fixed when it starts so that
          ticking another row behind the sheet cannot change it. Held here,
          not in the selection bar, which goes with an emptied list. */}
      {pickingIds && (
        <ListPickingSheet
          documentIds={pickingIds}
          onLeave={() => {
            setPickingIds(null);
            bulk.clearSelection();
          }}
        />
      )}

      {/* Confirm dialog */}
      {confirmAction && (
        <ConfirmDialog
          open={!!confirmAction}
          title={t(`confirmDialog.${confirmAction.type}Title`)}
          message={t(`confirmDialog.${confirmAction.type}Message`)}
          variant={
            confirmAction.type === "delete" || confirmAction.type === "cancel"
              ? "danger"
              : "default"
          }
          confirmLabel={t(`actions.${confirmAction.type}`)}
          onConfirm={handleAction}
          onCancel={() => setConfirmAction(null)}
        />
      )}

      <ConfirmDialog
        open={bulk.bulkConfirmOpen}
        title={t("bulk.confirmTitle")}
        message={t("bulk.confirmMessage", {
          count: bulk.selectedDrafts.length,
        })}
        confirmLabel={t("bulk.confirmDrafts", {
          count: bulk.selectedDrafts.length,
        })}
        onConfirm={bulk.handleBulkConfirm}
        onCancel={() => bulk.setBulkConfirmOpen(false)}
      />

      {/* Bulk delete confirm */}
      <ConfirmDialog
        open={bulk.bulkDeleteOpen}
        title={t("bulk.deleteTitle")}
        message={t("bulk.deleteConfirm", { count: bulk.selectedDrafts.length })}
        variant="danger"
        confirmLabel={t("actions.delete")}
        onConfirm={bulk.handleBulkDelete}
        onCancel={() => bulk.setBulkDeleteOpen(false)}
      />
    </div>
  );
}
