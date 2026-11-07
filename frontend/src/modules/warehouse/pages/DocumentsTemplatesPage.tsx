import { useRef, useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Download, Plus, Upload } from "lucide-react";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { Button } from "@/components/ui/Button";
import { TemplateEditorModal } from "@/modules/shared/components/TemplateEditorModal";
import { TemplateCard } from "@/modules/shared/components/TemplateCard";
import { TemplatesEmptyState } from "@/modules/shared/components/TemplatesEmptyState";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import LoadingSpinner from "@/components/LoadingSpinner";
import { InlineQueryError, QueryFailure } from "@/components/ui/QueryResult";
import {
  useBuiltInTemplates,
  useDocumentTemplates,
  useDeleteTemplate,
  useExportTemplate,
  useImportTemplate,
  useRefreshTemplateCopy,
  useSeedDefaultTemplates,
} from "@/modules/shared/hooks/useDocumentTemplates";
import { BuiltInTemplatePreview } from "@/modules/shared/components/BuiltInTemplatePreview";
import { downloadBlob } from "@/utils/helpers";
import type { DocumentTemplate } from "@/modules/shared/lib/templates";
import { toast } from "sonner";

/** The types a template can be written for — the SAME seven the document
 * picker offers, under the SAME labels the documents list prints as
 * badges. A template's type is a promise about what it prints; offering
 * layout families here (the old "Standard"/"PL PZ") promised nothing the
 * print endpoint could read. */
const TEMPLATE_TYPES = [
  "IN",
  "OUT",
  "INT",
  "INTERNAL_IN",
  "INTERNAL_OUT",
  "CORRECTION",
  "SCRAP",
] as const;

/** Not a document type: the packing slip prints a dispatch's packages, one
 * sheet each, and its default template is the one the slip prints from. */
const PACKING_SLIP = "PACKING_SLIP";

/** Not a document type either: the pick list prints a dispatch's or a pick
 * session's lines in walk order, and its default template is the one it
 * prints from. */
const PICK_LIST = "PICK_LIST";

/** The template types that are not document types. */
const OWN_TYPES = [PACKING_SLIP, PICK_LIST];

/** The localized description of each document placeholder token. */
const PLACEHOLDER_DESCRIPTIONS = [
  {
    key: "{{backorder_of_number}}",
    descriptionKey: "templates.placeholders.backorder_of_number",
  },
  {
    key: "{{code128_height_mm}}",
    descriptionKey: "templates.placeholders.code128_height_mm",
  },
  {
    key: "{{code128_img}}",
    descriptionKey: "templates.placeholders.code128_img",
  },
  {
    key: "{{code128_width_mm}}",
    descriptionKey: "templates.placeholders.code128_width_mm",
  },
  {
    key: "{{corrected_doc_number}}",
    descriptionKey: "templates.placeholders.corrected_doc_number",
  },
  {
    key: "{{doc_subtitle}}",
    descriptionKey: "templates.placeholders.doc_subtitle",
  },
  { key: "{{doc_title}}", descriptionKey: "templates.placeholders.doc_title" },
  { key: "{{doc_type}}", descriptionKey: "templates.placeholders.doc_type" },
  {
    key: "{{document.number}}",
    descriptionKey: "templates.placeholders.document.number",
  },
  {
    key: "{{document.type}}",
    descriptionKey: "templates.placeholders.document.type",
  },
  {
    key: "{{document.status}}",
    descriptionKey: "templates.placeholders.document.status",
  },
  {
    key: "{{document.created_at}}",
    descriptionKey: "templates.placeholders.document.created_at",
  },
  {
    key: "{{document.scheduled_date}}",
    descriptionKey: "templates.placeholders.document.scheduled_date",
  },
  {
    key: "{{document.external_reference}}",
    descriptionKey: "templates.placeholders.document.external_reference",
  },
  {
    key: "{{document.notes}}",
    descriptionKey: "templates.placeholders.document.notes",
  },
  {
    key: "{{document.lines}}",
    descriptionKey: "templates.placeholders.document.lines",
  },
  {
    key: "{{is_correction}}",
    descriptionKey: "templates.placeholders.is_correction",
  },
  {
    key: "{{is_external}}",
    descriptionKey: "templates.placeholders.is_external",
  },
  {
    key: "{{is_external_in}}",
    descriptionKey: "templates.placeholders.is_external_in",
  },
  {
    key: "{{is_external_out}}",
    descriptionKey: "templates.placeholders.is_external_out",
  },
  {
    key: "{{is_internal}}",
    descriptionKey: "templates.placeholders.is_internal",
  },
  {
    key: "{{is_internal_in}}",
    descriptionKey: "templates.placeholders.is_internal_in",
  },
  {
    key: "{{is_internal_out}}",
    descriptionKey: "templates.placeholders.is_internal_out",
  },
  {
    key: "{{is_scrap}}",
    descriptionKey: "templates.placeholders.is_scrap",
  },
  {
    key: "{{is_transfer}}",
    descriptionKey: "templates.placeholders.is_transfer",
  },
  {
    key: "{{issuer.name}}",
    descriptionKey: "templates.placeholders.issuer.name",
  },
  {
    key: "{{issuer.tax_id}}",
    descriptionKey: "templates.placeholders.issuer.tax_id",
  },
  {
    key: "{{issuer.address}}",
    descriptionKey: "templates.placeholders.issuer.address",
  },
  {
    key: "{{issuer.logo}}",
    descriptionKey: "templates.placeholders.issuer.logo",
  },
  {
    key: "{{partner.name}}",
    descriptionKey: "templates.placeholders.partner.name",
  },
  {
    key: "{{partner.code}}",
    descriptionKey: "templates.placeholders.partner.code",
  },
  {
    key: "{{partner.tax_id}}",
    descriptionKey: "templates.placeholders.partner.tax_id",
  },
  {
    key: "{{partner.address}}",
    descriptionKey: "templates.placeholders.partner.address",
  },
  {
    key: "{{print_dates}}",
    descriptionKey: "templates.placeholders.print_dates",
  },
  {
    key: "{{print_number}}",
    descriptionKey: "templates.placeholders.print_number",
  },
  {
    key: "{{print_status}}",
    descriptionKey: "templates.placeholders.print_status",
  },
  {
    key: "{{print_subtitle}}",
    descriptionKey: "templates.placeholders.print_subtitle",
  },
  {
    key: "{{print_title}}",
    descriptionKey: "templates.placeholders.print_title",
  },
  { key: "{{qr_img}}", descriptionKey: "templates.placeholders.qr_img" },
  {
    key: "{{qr_size_mm}}",
    descriptionKey: "templates.placeholders.qr_size_mm",
  },
  {
    key: "{{return_of_number}}",
    descriptionKey: "templates.placeholders.return_of_number",
  },
  {
    key: "{{scrap_reason}}",
    descriptionKey: "templates.placeholders.scrap_reason",
  },
  {
    key: "{{show_line_status}}",
    descriptionKey: "templates.placeholders.show_line_status",
  },
  {
    key: "{{show_payment}}",
    descriptionKey: "templates.placeholders.show_payment",
  },
  {
    key: "{{show_tax_column}}",
    descriptionKey: "templates.placeholders.show_tax_column",
  },
  {
    key: "{{show_value_columns}}",
    descriptionKey: "templates.placeholders.show_value_columns",
  },
  {
    key: "{{source_location}}",
    descriptionKey: "templates.placeholders.source_location",
  },
  {
    key: "{{target_location}}",
    descriptionKey: "templates.placeholders.target_location",
  },
  {
    key: "{{total_done}}",
    descriptionKey: "templates.placeholders.total_done",
  },
  {
    key: "{{total_expected}}",
    descriptionKey: "templates.placeholders.total_expected",
  },
  {
    key: "{{totals_by_unit}}",
    descriptionKey: "templates.placeholders.totals_by_unit",
  },
];

export default function DocumentsTemplatesPage() {
  const { t } = useTranslation(["warehouse", "common"]);
  const { setHeader } = useModulePageHeader();
  // Writing a template is a POST through the documents router, which asks for
  // `warehouse:write`. This screen offered "Add Template", "Edit" and "Delete"
  // to anyone who could reach it, opened the whole HTML editor, and let the
  // refusal arrive after the work.
  const canWrite = useCanWrite("warehouse");
  const {
    data: templates,
    isLoading,
    isError,
    error,
    refetch,
  } = useDocumentTemplates("warehouse");
  const deleteMutation = useDeleteTemplate("warehouse");
  const seedMutation = useSeedDefaultTemplates("warehouse");
  const refreshCopyMutation = useRefreshTemplateCopy("warehouse");
  const exportMutation = useExportTemplate("warehouse");
  const importMutation = useImportTemplate("warehouse");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const {
    data: builtIns = [],
    isError: builtInsFailed,
    error: builtInsError,
    refetch: refetchBuiltIns,
  } = useBuiltInTemplates("warehouse");
  const [previewOpen, setPreviewOpen] = useState(false);
  // Stable refs: the mutation result object is recreated every
  // render; depending on it in the header effect loops forever.
  const seedMutate = seedMutation.mutate;
  const seedIsPending = seedMutation.isPending;
  const { confirm, confirmDialogProps } = useConfirm();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<
    DocumentTemplate | undefined
  >();

  // The empty state carries its own "Load built-in templates" call to action,
  // so the header must not offer a second button of the same name next to it.
  const hasTemplates = !!templates && templates.length > 0;

  useEffect(() => {
    setHeader({
      title: t("templates.title"),
      subtitle: t("templates.subtitle"),
      actions: !canWrite ? undefined : (
        <div className="flex items-center gap-2">
          {hasTemplates && (
            <Button
              size="sm"
              variant="outline"
              leftIcon={<Download size={16} />}
              onClick={() => seedMutate()}
              disabled={seedIsPending}
            >
              {t("common:templates.seed_defaults", "Load built-in templates")}
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            leftIcon={<Upload size={16} />}
            onClick={() => fileInputRef.current?.click()}
            disabled={importMutation.isPending}
          >
            {t("common:templates.import", "Import template")}
          </Button>
          <Button
            size="sm"
            leftIcon={<Plus size={16} />}
            onClick={() => {
              setEditingTemplate(undefined);
              setEditorOpen(true);
            }}
          >
            {t("common:templates.add", "Add Template")}
          </Button>
        </div>
      ),
    });
  }, [
    t,
    setHeader,
    seedMutate,
    seedIsPending,
    hasTemplates,
    canWrite,
    importMutation.isPending,
  ]);

  const handleDelete = async (tpl: DocumentTemplate) => {
    const ok = await confirm({
      title: t("common:templates.deleteTitle", "Delete template"),
      message: t("templates.confirm_delete", { name: tpl.name }),
      variant: "danger",
      confirmLabel: t("common:actions.delete", "Delete"),
    });
    if (ok) {
      deleteMutation.mutate(tpl.id);
    }
  };

  // The organization's own copy is left exactly as it is — the
  // refreshed layout arrives beside it, and it says so.
  const handleRefreshCopy = (tpl: DocumentTemplate) => {
    refreshCopyMutation.mutate(tpl.id, {
      onSuccess: (created) =>
        toast.success(
          t("common:templates.refreshedCopy", { name: created.name }),
        ),
    });
  };

  // A template leaves under its own name; the file itself is the message,
  // so the download is silent and only a failure is announced.
  const handleExport = (tpl: DocumentTemplate) => {
    exportMutation.mutate(tpl.id, {
      onSuccess: (blob) => downloadBlob(blob, `${tpl.name}.json`),
    });
  };

  const handleImportFile = (file: File) => {
    importMutation.mutate(file, {
      onSuccess: (created) =>
        toast.success(t("common:templates.imported", { name: created.name })),
    });
  };

  // The badge speaks the same vocabulary as the dialog's Type field: the
  // documents list's own labels for the seven document types, and honest
  // family names for the legacy copies of the built-ins (which were born
  // before templates carried a document type at all).
  const TYPE_LABELS: Record<string, string> = {
    ...Object.fromEntries(
      TEMPLATE_TYPES.map((value) => [value, t(`types.${value}`)]),
    ),
    STANDARD: t("templates.type_standard", "Standard"),
    PL_PZ: t("templates.type_pl_pz", "PL PZ"),
    [PACKING_SLIP]: t("templates.type_packing_slip"),
    [PICK_LIST]: t("templates.type_pick_list"),
  };

  // The API names its built-in layouts once, in English; the preview's
  // picker calls them what the print-layout picker and the empty screen do.
  const BUILT_IN_NAMES: Record<string, string> = {
    STANDARD: t("profile.layoutStandard"),
    PL_PZ: t("profile.layoutPlPz"),
    [PACKING_SLIP]: t("templates.type_packing_slip"),
    [PICK_LIST]: t("templates.type_pick_list"),
  };
  const namedBuiltIns = builtIns.map((tpl) => ({
    ...tpl,
    name: BUILT_IN_NAMES[tpl.document_type] ?? tpl.name,
  }));

  return (
    <div className="space-y-6">
      {/* A screen that used to carry three buttons and now carries none reads
          as broken rather than as a boundary. The documents list and the
          putaway rules have said this for a while; this one said nothing. */}
      <ReadOnlyNotice module="warehouse" />
      {/* The built-in layouts feed the preview; without them its entry point
          silently disappears. */}
      {builtInsFailed && (
        <InlineQueryError
          error={builtInsError}
          onRetry={() => void refetchBuiltIns()}
        />
      )}
      {isError ? (
        <QueryFailure
          error={error}
          message={t("errors.loadTemplatesFailed")}
          onRetry={() => refetch()}
        />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : !templates || templates.length === 0 ? (
        <TemplatesEmptyState
          emptyMessage={t("templates.empty")}
          onPreview={
            builtIns.length > 0 ? () => setPreviewOpen(true) : undefined
          }
          previewLabel={t("templates.builtInPreviewAction")}
          onSeed={() => seedMutation.mutate()}
          onCreate={() => {
            setEditingTemplate(undefined);
            setEditorOpen(true);
          }}
          isSeedPending={seedMutation.isPending}
          readOnly={!canWrite}
          seedLabel={t("common:templates.seed_defaults")}
          createLabel={t(
            "common:templates.create_first",
            "Create your first template",
          )}
        />
      ) : (
        <div className="space-y-2">
          {templates.map((tpl) => (
            <TemplateCard
              key={tpl.id}
              template={tpl}
              typeLabels={TYPE_LABELS}
              onEdit={(t) => {
                setEditingTemplate(t);
                setEditorOpen(true);
              }}
              onDelete={handleDelete}
              readOnly={!canWrite}
              defaultLabel={t("common:templates.default", "Default")}
              onRefreshCopy={handleRefreshCopy}
              isRefreshPending={refreshCopyMutation.isPending}
              onExport={handleExport}
            />
          ))}
        </div>
      )}

      {editorOpen && (
        <TemplateEditorModal
          module="warehouse"
          previewSupported
          template={editingTemplate}
          documentTypes={[
            ...TEMPLATE_TYPES.map((value) => ({
              value,
              label: t(`types.${value}`),
            })),
            ...OWN_TYPES.map((value) => ({
              value,
              label: TYPE_LABELS[value],
            })),
            // A legacy copy of a built-in carries a layout-family type the
            // seven document types don't include. The editor must still
            // offer it: a select whose options lack the current value
            // renders its first option instead, and saving through that
            // shown value silently rewrote the template's type.
            ...(editingTemplate?.document_type &&
            !([...TEMPLATE_TYPES, ...OWN_TYPES] as string[]).includes(
              editingTemplate.document_type,
            )
              ? [
                  {
                    value: editingTemplate.document_type,
                    label:
                      TYPE_LABELS[editingTemplate.document_type] ??
                      editingTemplate.document_type,
                  },
                ]
              : []),
          ]}
          onClose={() => setEditorOpen(false)}
          i18nNamespace="warehouse"
          placeholderDescriptions={PLACEHOLDER_DESCRIPTIONS}
        />
      )}
      <BuiltInTemplatePreview
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        templates={namedBuiltIns}
        module="warehouse"
      />
      {/* The import picker: never painted, opened by the header button. */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        aria-hidden="true"
        tabIndex={-1}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) handleImportFile(file);
          // Picking the same file twice must still fire.
          e.target.value = "";
        }}
      />
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
