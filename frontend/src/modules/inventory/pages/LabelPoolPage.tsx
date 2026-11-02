import { extractApiError } from "@/lib/errors";
import { useState, useEffect, useCallback, useMemo } from "react";
import { Plus, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { downloadBlob } from "@/utils/helpers";
import {
  useLabels,
  useDeleteLabel,
  useBulkDeleteLabels,
  useExportLabelPng,
} from "@/modules/shared/hooks/useLabels";
import { toast } from "sonner";
import { useSettingsStore } from "@/store/settingsStore";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { LabelCard } from "@/modules/inventory/components/labels/LabelCard";
import { LabelRow } from "@/modules/inventory/components/labels/LabelRow";
import { LabelGenerateModal } from "@/modules/inventory/components/labels/LabelGenerateModal";
import {
  LabelPreviewModal,
  type PrintSettings,
} from "@/modules/inventory/components/labels/LabelPreviewModal";
import Button from "@/components/ui/Button";
import { LabelPoolEmptyState } from "@/modules/inventory/components/labels/LabelPoolEmptyState";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { QueryError } from "@/components/ui/QueryResult";
import Pagination from "@/components/ui/Pagination";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { BulkActionBar } from "@/modules/inventory/components/labels/BulkActionBar";
import { PrintQueuePanel } from "@/modules/inventory/components/labels/PrintQueuePanel";
import { useLabelStatusTabs } from "@/modules/inventory/hooks/useLabelStateName";
import { LabelPageSelectAll } from "@/modules/inventory/components/labels/LabelPageSelectAll";

const PAGE_SIZE = 50;

export default function LabelPoolPage() {
  const { t } = useTranslation(["labels", "common"]);
  const { setHeader } = useModulePageHeader();
  // The printing module has no endpoints of its own — the pool lives in the
  // Core labels API, which asks for `items:write` on every mutating route.
  // Exporting a sheet is a GET there and stays open to a reader.
  const canWrite = useCanWrite("items");
  const { confirm, confirmDialogProps } = useConfirm();
  const statusTabs = useLabelStatusTabs();
  const {
    publicUrl,
    defaultLabelWidth,
    defaultLabelHeight,
    defaultLabelPrefix,
  } = useSettingsStore();

  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [previewIds, setPreviewIds] = useState<string[]>([]);
  // The pool opens on everything it holds. Opening on FREE meant a page full
  // of printed labels reported "No labels found" — an answer about the filter,
  // read as an answer about the account.
  const [filterStatus, setFilterStatus] = useState<string>("ALL");
  const [offset, setOffset] = useState(0);
  const [viewMode, setViewMode] = useState<"grid" | "list">("list");
  const [showGenForm, setShowGenForm] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    setHeader({
      title: t("title"),
      actions: canWrite ? (
        <div className="ml-auto">
          <Button
            onClick={() => setShowGenForm(true)}
            leftIcon={<Plus size={16} />}
            className="shrink-0"
          >
            <span>{t("actions.generate")}</span>
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);
  const [printSettings, setPrintSettings] = useState<PrintSettings>({
    width: defaultLabelWidth,
    height: defaultLabelHeight,
    publicUrl,
    customDescription: "",
    qrOnly: false,
    copiesPerLabel: 1,
    // A shelf is read by caption, not by short code.
    showCode: false,
  });
  const [genData, setGenData] = useState({
    count: 1,
    prefix: defaultLabelPrefix,
    label_type: "GENERIC",
    description: "",
    target_location_id: "",
    context_tag: "",
  });

  useEffect(() => {
    setPrintSettings((prev) => ({
      ...prev,
      width: defaultLabelWidth,
      height: defaultLabelHeight,
      publicUrl,
    }));
    if (!showGenForm) {
      // Closing the form drops the batch's purpose along with its prefix —
      // the next batch starts from the installation default rather than
      // silently inheriting the last one's tag.
      setGenData((prev) => ({
        ...prev,
        prefix: defaultLabelPrefix,
        context_tag: "",
      }));
    }
  }, [
    defaultLabelWidth,
    defaultLabelHeight,
    publicUrl,
    defaultLabelPrefix,
    showGenForm,
  ]);

  const { data, isLoading, isError, refetch } = useLabels(false, undefined, {
    status: filterStatus === "ALL" ? undefined : filterStatus,
    offset,
    limit: PAGE_SIZE,
  });
  // useMemo is REQUIRED: ``data?.items ?? []`` creates a new array reference
  // on every render while data is undefined, which would re-fire the
  // ``useEffect([selectedIds, labels])`` below in an infinite render loop.
  const labels = useMemo(() => data?.items ?? [], [data?.items]);
  const total = data?.total ?? 0;

  useEffect(() => {
    if (previewIds.length === 1 && labels) {
      const label = labels.find((l) => l.id === previewIds[0]);
      setPrintSettings((prev) => ({
        ...prev,
        customDescription: label?.description || "",
      }));
    } else {
      setPrintSettings((prev) => ({ ...prev, customDescription: "" }));
    }
  }, [previewIds, labels]);

  // A page of freshly generated labels has neither descriptions nor items:
  // rather than a column of dashes, drop the column.
  const showDescription = labels.some(
    (l) => Boolean(l.description) || Boolean(l.assigned_item_name),
  );

  const previewLabels = labels.filter((l) => previewIds.includes(l.id)) || [];
  const deleteMutation = useDeleteLabel();
  const bulkDeleteMutation = useBulkDeleteLabels();
  const exportLabelPng = useExportLabelPng();

  const handleToggleSelect = useCallback(
    (id: string) =>
      setSelectedIds((prev) =>
        prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id],
      ),
    [],
  );

  const handleDeleteLabel = useCallback(
    async (id: string, e: React.MouseEvent) => {
      e.stopPropagation();
      if (
        await confirm({
          title: t("common:actions.delete"),
          message: t("common:messages.confirmDelete"),
          variant: "danger",
          confirmLabel: t("common:actions.delete"),
        })
      ) {
        deleteMutation.mutate(id, {
          onSuccess: (_, deletedId) => {
            setSelectedIds((prev) => prev.filter((item) => item !== deletedId));
            toast.success(t("labelDeleted"));
          },
        });
      }
    },
    [confirm, deleteMutation, t],
  );

  const handlePreviewSingle = useCallback((id: string) => {
    setPreviewIds([id]);
    setShowPreview(true);
  }, []);

  const handleDownloadPreview = async () => {
    if (previewIds.length === 0) return;
    try {
      const copies = printSettings.copiesPerLabel ?? 1;
      const expandedIds = previewIds.flatMap((id) => Array(copies).fill(id));
      const blob = await exportLabelPng.mutateAsync({
        count: expandedIds.length,
        labelIds: expandedIds,
        width: printSettings.width,
        height: printSettings.height,
        baseUrl: printSettings.publicUrl,
        description: printSettings.customDescription || undefined,
        qrOnly: printSettings.qrOnly || undefined,
        showCode: printSettings.showCode || undefined,
      });
      const totalCount = expandedIds.length;
      const filename =
        previewLabels.length === 1
          ? copies > 1
            ? `${previewLabels[0].short_code}_x${copies}.png`
            : `${previewLabels[0].short_code}.png`
          : `labels_batch_${totalCount}pcs.png`;
      downloadBlob(blob, filename);
      setShowPreview(false);
    } catch (error) {
      toast.error(extractApiError(error, t("errorDownloading")));
    }
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="items" />
      {selectedIds.length > 0 && canWrite && (
        <BulkActionBar
          selectedIds={selectedIds}
          bulkDeleteMutation={bulkDeleteMutation}
          onClearSelection={() => setSelectedIds([])}
          onDeleteSelected={async () => {
            if (
              await confirm({
                title: t("common:actions.delete"),
                message: t("common:messages.confirmDelete"),
                variant: "danger",
                confirmLabel: t("common:actions.delete"),
              })
            ) {
              bulkDeleteMutation.mutate(selectedIds, {
                onSuccess: () => {
                  setSelectedIds([]);
                  toast.success(t("labelDeleted"));
                },
              });
            }
          }}
          onPreviewSelected={() => {
            setPreviewIds(selectedIds);
            setShowPreview(true);
          }}
          t={t}
        />
      )}

      <ListControlBar
        primaryTabs={{
          value: filterStatus,
          onChange: (v) => {
            setFilterStatus(v);
            setOffset(0);
          },
          options: statusTabs,
        }}
        viewToggle={{ mode: viewMode, onChange: setViewMode }}
        resultCount={isError ? undefined : total}
        resultCountLabel={t("filters.found", { count: total })}
      />

      <div>
        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-20">
            <Loader2 size={40} className="animate-spin text-primary-600 mb-4" />
            <p className="text-on-secondary font-medium">
              {t("status.loading")}
            </p>
          </div>
        ) : isError ? (
          /* Not an empty pool: the codes are on shelves, and "generate the
             first labels" would print a second set of the same numbers. */
          <QueryError onRetry={refetch} />
        ) : labels && labels.length > 0 ? (
          viewMode === "grid" ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 3xl:grid-cols-6 gap-4">
              {labels.map((label) => (
                <LabelCard
                  key={label.id}
                  label={label}
                  isSelected={selectedIds.includes(label.id)}
                  onToggleSelect={() => handleToggleSelect(label.id)}
                  onPreviewSingle={() => handlePreviewSingle(label.id)}
                  onDelete={(e) => handleDeleteLabel(label.id, e)}
                  canWrite={canWrite}
                />
              ))}
            </div>
          ) : (
            <div className="bg-surface-card rounded-xl sm:rounded-2xl shadow-sm border border-border overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-surface-raised border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
                    <th className="pl-3 sm:pl-5 pr-0 py-3 sm:py-4 w-10">
                      <LabelPageSelectAll
                        labels={labels}
                        selectedIds={selectedIds}
                        setSelectedIds={setSelectedIds}
                      />
                    </th>
                    <th className="px-2 sm:px-4 py-3 sm:py-4">
                      {t("previewModal.labelCode")}
                    </th>
                    {showDescription && (
                      <th className="px-2 sm:px-4 py-3 sm:py-4 hidden sm:table-cell">
                        {t("generateModal.description")}
                      </th>
                    )}
                    <th className="px-2 sm:px-4 py-3 sm:py-4 hidden md:table-cell">
                      {t("previewModal.type")}
                    </th>
                    <th className="px-2 sm:px-4 py-3 sm:py-4">
                      {t("previewModal.status")}
                    </th>
                    <th className="px-2 sm:px-4 py-3 sm:py-4 text-right">
                      {t("common:actions.title")}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {labels.map((label) => (
                    <LabelRow
                      key={label.id}
                      label={label}
                      isSelected={selectedIds.includes(label.id)}
                      onToggleSelect={() => handleToggleSelect(label.id)}
                      onPreviewSingle={() => handlePreviewSingle(label.id)}
                      onDelete={(e) => handleDeleteLabel(label.id, e)}
                      canWrite={canWrite}
                      showDescription={showDescription}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <LabelPoolEmptyState
            filtered={filterStatus !== "ALL"}
            onGenerate={() => setShowGenForm(true)}
            canWrite={canWrite}
            onShowAll={() => {
              setFilterStatus("ALL");
              setOffset(0);
            }}
          />
        )}
      </div>

      <Pagination
        skip={offset}
        limit={PAGE_SIZE}
        total={total}
        onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
        onNext={() => setOffset(offset + PAGE_SIZE)}
      />

      <PrintQueuePanel />

      <LabelGenerateModal
        open={showGenForm}
        onClose={() => setShowGenForm(false)}
        onGenerated={() => {
          // New labels are FREE; a tab that excludes them shows the old rows.
          setFilterStatus((tab) => (tab === "ALL" ? tab : "FREE"));
          setOffset(0);
        }}
        genData={genData}
        setGenData={setGenData}
        defaultPrefix={defaultLabelPrefix}
      />

      <LabelPreviewModal
        open={showPreview}
        onClose={() => setShowPreview(false)}
        selectedLabels={previewLabels}
        printSettings={printSettings}
        setPrintSettings={setPrintSettings}
        onDownload={handleDownloadPreview}
      />

      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
