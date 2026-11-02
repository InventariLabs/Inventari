import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Download, Plus, Monitor, FileText } from "lucide-react";
import { toast } from "sonner";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { Button } from "@/components/ui/Button";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryError } from "@/components/ui/QueryResult";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/Tabs";
import {
  useEquipmentModels,
  useCreateEquipmentModel,
  useUpdateEquipmentModel,
  useDeleteEquipmentModel,
  useCloneEquipmentModel,
} from "@/modules/equipment/hooks/useEquipment";
import {
  useDocumentTemplates,
  useDeleteTemplate,
  useSeedDefaultTemplates,
  useRefreshTemplateCopy,
} from "@/modules/shared/hooks/useDocumentTemplates";
import { TemplatesEmptyState } from "@/modules/shared/components/TemplatesEmptyState";
import { TemplateCard } from "@/modules/shared/components/TemplateCard";
import { TemplateEditorModal } from "@/modules/shared/components/TemplateEditorModal";
import { ModelCatalog } from "@/modules/equipment/components/ModelCatalog";
import ModelEditModal from "@/modules/equipment/components/ModelEditModal";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";
import type { DocumentTemplate } from "@/modules/shared/lib/templates";
import { extractApiError } from "@/lib/errors";

/** The localized description of each protocol placeholder token. */
const PLACEHOLDER_DESCRIPTIONS = [
  { key: "{{item_name}}", descriptionKey: "templates.placeholders.item_name" },
  {
    key: "{{item_barcode}}",
    descriptionKey: "templates.placeholders.item_barcode",
  },
  {
    key: "{{category_name}}",
    descriptionKey: "templates.placeholders.category_name",
  },
  {
    key: "{{serial_number}}",
    descriptionKey: "templates.placeholders.serial_number",
  },
  { key: "{{asset_tag}}", descriptionKey: "templates.placeholders.asset_tag" },
  {
    key: "{{manufacturer}}",
    descriptionKey: "templates.placeholders.manufacturer",
  },
  { key: "{{model}}", descriptionKey: "templates.placeholders.model" },
  {
    key: "{{manufacturer_model}}",
    descriptionKey: "templates.placeholders.manufacturer_model",
  },
  {
    key: "{{custom.<key>}}",
    descriptionKey: "templates.placeholders.custom_field",
  },
  {
    key: "{{checkout_location_name}}",
    descriptionKey: "templates.placeholders.checkout_location_name",
  },
  {
    key: "{{assigned_to_name}}",
    descriptionKey: "templates.placeholders.assigned_to_name",
  },
  {
    key: "{{assigned_to_email}}",
    descriptionKey: "templates.placeholders.assigned_to_email",
  },
  {
    key: "{{checked_out_at}}",
    descriptionKey: "templates.placeholders.checked_out_at",
  },
  {
    key: "{{checked_in_at}}",
    descriptionKey: "templates.placeholders.checked_in_at",
  },
  {
    key: "{{expected_return_at}}",
    descriptionKey: "templates.placeholders.expected_return_at",
  },
  {
    key: "{{checkout_notes}}",
    descriptionKey: "templates.placeholders.checkout_notes",
  },
  {
    key: "{{checkin_notes}}",
    descriptionKey: "templates.placeholders.checkin_notes",
  },
  {
    key: "{{checkin_condition}}",
    descriptionKey: "templates.placeholders.checkin_condition",
  },
  {
    key: "{{issued_by_name}}",
    descriptionKey: "templates.placeholders.issued_by_name",
  },
  {
    key: "{{issued_by_email}}",
    descriptionKey: "templates.placeholders.issued_by_email",
  },
  {
    key: "{{organization_name}}",
    descriptionKey: "templates.placeholders.organization_name",
  },
  {
    key: "{{document_date}}",
    descriptionKey: "templates.placeholders.document_date",
  },
  {
    key: "{{document_number}}",
    descriptionKey: "templates.placeholders.document_number",
  },
];

export default function TemplatesPage() {
  const { t } = useTranslation(["equipment", "common"]);
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("equipment");
  const {
    data: templates,
    isLoading,
    isError,
    refetch,
  } = useDocumentTemplates("equipment");
  const deleteTemplateMutation = useDeleteTemplate("equipment");
  const seedMutation = useSeedDefaultTemplates("equipment");
  const refreshCopyMutation = useRefreshTemplateCopy("equipment");
  const {
    data: models = [],
    isLoading: modelsLoading,
    isError: modelsError,
    refetch: refetchModels,
  } = useEquipmentModels();
  const { confirm, confirmDialogProps } = useConfirm();

  const createModelMutation = useCreateEquipmentModel();
  const updateModelMutation = useUpdateEquipmentModel();
  const deleteModelMutation = useDeleteEquipmentModel();
  const cloneModelMutation = useCloneEquipmentModel();

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] = useState<
    DocumentTemplate | undefined
  >();

  const [modelEditorOpen, setModelEditorOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<EquipmentModel | null>(null);
  const [activeTab, setActiveTab] = useState("documents");

  const isModelSubmitting =
    createModelMutation.isPending || updateModelMutation.isPending;

  const seedMutate = seedMutation.mutate;
  const seedPending = seedMutation.isPending;

  const seedButton = useMemo(
    () => (
      <Button
        size="sm"
        variant="outline"
        leftIcon={<Download size={16} />}
        onClick={() => seedMutate()}
        disabled={seedPending}
      >
        {t("common:templates.seed_defaults", "Load built-in templates")}
      </Button>
    ),
    [seedMutate, seedPending, t],
  );

  useEffect(() => {
    if (activeTab === "documents") {
      setHeader({
        title: t("templates.pageTitle"),
        subtitle: t("templates.subtitle"),
        actions: canWrite ? (
          <div className="flex items-center gap-2">
            {seedButton}
            <Button
              leftIcon={<Plus size={16} />}
              onClick={() => {
                setEditingTemplate(undefined);
                setEditorOpen(true);
              }}
            >
              {t("common:templates.add", "Add Template")}
            </Button>
          </div>
        ) : undefined,
      });
    } else {
      setHeader({
        title: t("templates.pageTitle"),
        subtitle: t("models.subtitle"),
        actions: canWrite ? (
          <Button
            leftIcon={<Plus size={16} />}
            onClick={() => {
              setEditingModel(null);
              setModelEditorOpen(true);
            }}
          >
            {t("models.create", "Create Model")}
          </Button>
        ) : undefined,
      });
    }
  }, [t, setHeader, activeTab, seedButton, canWrite]);

  const handleDelete = async (tpl: DocumentTemplate) => {
    const ok = await confirm({
      title: t("common:templates.deleteTitle", "Delete template"),
      message: t("templates.confirm_delete", { name: tpl.name }),
      variant: "danger",
      confirmLabel: t("common:actions.delete"),
    });
    if (ok) {
      deleteTemplateMutation.mutate(tpl.id);
    }
  };

  const handleDeleteModel = async (model: EquipmentModel) => {
    const ok = await confirm({
      title: t("models.deleteTitle", "Delete model"),
      message: t("models.confirmDelete", { name: model.name }),
      variant: "danger",
      confirmLabel: t("common:actions.delete"),
    });
    if (ok) {
      deleteModelMutation.mutate(model.id);
    }
  };

  const handleCloneModel = (model: EquipmentModel) => {
    cloneModelMutation.mutate(model.id, {
      onSuccess: () => toast.success(t("models.cloned", "Model cloned")),
      onError: (err) =>
        toast.error(
          extractApiError(
            err,
            t("models.cloneFailed", "Failed to clone model"),
          ),
        ),
    });
  };

  const handleSaveModel = (data: {
    name: string;
    brand: string;
    description: string;
    category_id: string | null;
    equipment_meta: Record<string, unknown>;
  }) => {
    if (editingModel) {
      updateModelMutation.mutate(
        { modelId: editingModel.id, data },
        {
          onSuccess: () => {
            toast.success(t("models.updated", "Model updated"));
            setModelEditorOpen(false);
          },
          onError: (err) =>
            toast.error(
              extractApiError(
                err,
                t("models.updateFailed", "Failed to update model"),
              ),
            ),
        },
      );
    } else {
      createModelMutation.mutate(data, {
        onSuccess: () => {
          toast.success(t("models.created", "Model created"));
          setModelEditorOpen(false);
        },
        onError: (err) =>
          toast.error(
            extractApiError(
              err,
              t("models.createFailed", "Failed to create model"),
            ),
          ),
      });
    }
  };

  // The organization's own copy is left exactly as it is — the refreshed
  // layout arrives beside it, and it says so.
  const handleRefreshCopy = (tpl: DocumentTemplate) => {
    refreshCopyMutation.mutate(tpl.id, {
      onSuccess: (created) =>
        toast.success(
          t("common:templates.refreshedCopy", { name: created.name }),
        ),
    });
  };

  const TYPE_LABELS: Record<string, string> = {
    CHECKOUT: t("templates.type_checkout", "Checkout"),
    CHECKIN: t("templates.type_checkin", "Check-in"),
    UNIVERSAL: t("templates.type_universal", "Universal"),
  };

  const handleEdit = (tpl: DocumentTemplate) => {
    setEditingTemplate(tpl);
    setEditorOpen(true);
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="equipment" />
      <Tabs
        defaultValue="documents"
        value={activeTab}
        onValueChange={setActiveTab}
      >
        <TabsList className="w-full mb-5">
          <TabsTrigger value="documents">
            <FileText size={14} className="mr-1.5" />
            {t("templates.title", "Document Templates")}
          </TabsTrigger>
          <TabsTrigger value="models">
            <Monitor size={14} className="mr-1.5" />
            {t("models.title", "Equipment Models")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="documents">
          {isError ? (
            <QueryError onRetry={() => refetch()} />
          ) : isLoading ? (
            <LoadingSpinner />
          ) : !templates || templates.length === 0 ? (
            <TemplatesEmptyState
              emptyMessage={t(
                "templates.empty",
                "No custom templates yet. The built-in default will be used for protocols.",
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
                  template={tpl}
                  typeLabels={TYPE_LABELS}
                  onEdit={handleEdit}
                  onDelete={handleDelete}
                  defaultLabel={t("common:templates.default", "Default")}
                  onRefreshCopy={handleRefreshCopy}
                  isRefreshPending={refreshCopyMutation.isPending}
                  readOnly={!canWrite}
                />
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="models">
          <ModelCatalog
            models={models}
            isLoading={modelsLoading}
            isError={modelsError}
            onRetry={() => refetchModels()}
            onEdit={(m) => {
              setEditingModel(m);
              setModelEditorOpen(true);
            }}
            onClone={handleCloneModel}
            onDelete={handleDeleteModel}
            readOnly={!canWrite}
            isClonePending={cloneModelMutation.isPending}
            isDeletePending={deleteModelMutation.isPending}
          />
        </TabsContent>
      </Tabs>

      {editorOpen && (
        <TemplateEditorModal
          module="equipment"
          template={editingTemplate}
          // One label per value, and the same one the card shows. The
          // editor used to carry its own untranslated set, so a template
          // saved as "Checkout (Handover)" was listed as "Checkout".
          documentTypes={Object.entries(TYPE_LABELS).map(([value, label]) => ({
            value,
            label,
          }))}
          onClose={() => setEditorOpen(false)}
          i18nNamespace="equipment"
          placeholderDescriptions={PLACEHOLDER_DESCRIPTIONS}
        />
      )}

      <ModelEditModal
        key={editingModel?.id ?? "new"}
        isOpen={modelEditorOpen}
        model={editingModel}
        isSubmitting={isModelSubmitting}
        onSave={handleSaveModel}
        onClose={() => {
          setModelEditorOpen(false);
          setEditingModel(null);
        }}
      />

      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
