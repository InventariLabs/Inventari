import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
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
import {
  useDocumentTemplates,
  useDeleteTemplate,
  useSeedDefaultTemplates,
} from "@/modules/shared/hooks/useDocumentTemplates";
import { QueryError } from "@/components/ui/QueryResult";
import type { DocumentTemplate } from "@/modules/shared/lib/templates";

const DOCUMENT_TYPES = [
  { value: "STANDARD", labelKey: "templates.documentType.standard" },
];

/** The localized description of each PO placeholder token. */
const PLACEHOLDER_DESCRIPTIONS = [
  { key: "{{po_number}}", descriptionKey: "templates.placeholders.po_number" },
  { key: "{{po_date}}", descriptionKey: "templates.placeholders.po_date" },
  { key: "{{po_status}}", descriptionKey: "templates.placeholders.po_status" },
  { key: "{{po_title}}", descriptionKey: "templates.placeholders.po_title" },
  {
    key: "{{vendor_name}}",
    descriptionKey: "templates.placeholders.vendor_name",
  },
  {
    key: "{{vendor_tax_id}}",
    descriptionKey: "templates.placeholders.vendor_tax_id",
  },
  {
    key: "{{vendor_address}}",
    descriptionKey: "templates.placeholders.vendor_address",
  },
  { key: "{{total_net}}", descriptionKey: "templates.placeholders.total_net" },
  { key: "{{total_tax}}", descriptionKey: "templates.placeholders.total_tax" },
  {
    key: "{{total_gross}}",
    descriptionKey: "templates.placeholders.total_gross",
  },
  {
    key: "{{lines_count}}",
    descriptionKey: "templates.placeholders.lines_count",
  },
  {
    key: "{{organization_name}}",
    descriptionKey: "templates.placeholders.organization_name",
  },
  {
    key: "{{barcode_img}}",
    descriptionKey: "templates.placeholders.barcode_img",
  },
  { key: "{{qr_img}}", descriptionKey: "templates.placeholders.qr_img" },
  { key: "{{currency}}", descriptionKey: "templates.placeholders.currency" },
];

export default function PurchaseOrdersTemplatesPage() {
  const { t } = useTranslation(["purchase_orders", "common"]);
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("purchase_orders");
  // "purchase-orders" is the API URL segment; the module directory
  // name "purchase_orders" produced a silent 404 and a fake empty state.
  const {
    data: templates,
    isLoading,
    isError,
    refetch,
  } = useDocumentTemplates("purchase-orders");
  const deleteMutation = useDeleteTemplate("purchase-orders");
  const seedMutation = useSeedDefaultTemplates("purchase-orders");
  const { confirm, confirmDialogProps } = useConfirm();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<
    DocumentTemplate | undefined
  >();

  useEffect(() => {
    setHeader({
      backTo: "/purchase-orders",
      title: t("templates.title"),
      subtitle: t("templates.subtitle"),
      // at zero records the two CTAs belong to the empty state, not a
      // header repeating the same buttons. With records present, keep "Add
      // Template" reachable from the top; "Load built-in templates" is a seed
      // action and stays only in the empty state.
      actions:
        canWrite && templates && templates.length > 0 ? (
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
        ) : undefined,
    });
  }, [t, setHeader, templates, canWrite]);

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

  const TYPE_LABELS: Record<string, string> = {
    STANDARD: t("templates.type_standard", "Standard"),
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="purchase_orders" />
      {isLoading ? (
        <LoadingSpinner />
      ) : isError ? (
        <QueryError
          onRetry={() => refetch()}
          message={t("templates.load_error", "Failed to load templates.")}
        />
      ) : !templates || templates.length === 0 ? (
        <TemplatesEmptyState
          readOnly={!canWrite}
          emptyMessage={t(
            "templates.empty",
            "No custom templates yet. The built-in template will be used for PO PDFs.",
          )}
          onSeed={() => seedMutation.mutate()}
          onCreate={() => {
            setEditingTemplate(undefined);
            setEditorOpen(true);
          }}
          isSeedPending={seedMutation.isPending}
          seedLabel={t(
            "common:templates.seed_defaults",
            "Load built-in templates",
          )}
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
              readOnly={!canWrite}
              template={tpl}
              typeLabels={TYPE_LABELS}
              onEdit={(t) => {
                setEditingTemplate(t);
                setEditorOpen(true);
              }}
              onDelete={handleDelete}
              defaultLabel={t("common:templates.default", "Default")}
            />
          ))}
        </div>
      )}

      {editorOpen && (
        <TemplateEditorModal
          module="purchase-orders"
          template={editingTemplate}
          documentTypes={DOCUMENT_TYPES.map((dt) => ({
            value: dt.value,
            label: t(dt.labelKey),
          }))}
          onClose={() => setEditorOpen(false)}
          i18nNamespace="purchase_orders"
          namePlaceholder={t("templates.namePlaceholder")}
          htmlInvalidMessage={t("templates.htmlInvalid")}
          placeholderDescriptions={PLACEHOLDER_DESCRIPTIONS}
        />
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
