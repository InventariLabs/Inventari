import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { extractApiError, extractApiErrorCode } from "@/lib/errors";
import { RECIPES_PURPOSE_KEY } from "@/modules/recipes/components/RecipesAiSettings";
import {
  useCreateRecipe,
  usePreviewImport,
} from "@/modules/recipes/hooks/useRecipes";
import { useAiPurposes } from "@/modules/settings/hooks/useAiConnections";
import { ImportModal } from "./ImportModal";
import ImportReviewModal from "./ImportReviewModal";
import type { TFunction } from "i18next";
import type { Recipe, RecipeCreateInput } from "@/modules/recipes/types/core";
import type { RecipeImportPreview } from "@/modules/recipes/types/nutrition";

type ImportMode = "url" | "json";

interface RecipeImportManagerProps {
  t: TFunction;
  onClose: () => void;
  onImported: (recipe: Recipe) => void;
}

/**
 * RecipeImportManager — owns the recipe import flow (URL/JSON preview, then the
 * review modal). The parent mounts it via `{showImport && ...}` and navigates
 * away on a successful import via `onImported`.
 */
export function RecipeImportManager({
  t,
  onClose,
  onImported,
}: RecipeImportManagerProps) {
  const [importMode, setImportMode] = useState<ImportMode>("url");
  const [importUrl, setImportUrl] = useState("");
  const [importJson, setImportJson] = useState("");
  const [importPreview, setImportPreview] =
    useState<RecipeImportPreview | null>(null);
  const [modalOpen, setModalOpen] = useState(true);
  const [importError, setImportError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [askReplaceWithExample, setAskReplaceWithExample] = useState(false);

  const previewMutation = usePreviewImport();
  const createMutation = useCreateRecipe();

  // The AI purpose registry knows before any click whether URL import can
  // work. Only a registry that answered and refused the purpose blocks the
  // tab — a registry that failed to load stays out of the way and lets the
  // attempt travel to the backend, which answers with the same verdict
  // under its own code. The refusal is `usable`'s to tell: the raw
  // binding can name a connection the rules refuse, and a text binding
  // elsewhere does not make this one run.
  // The registry only pre-empts a refusal the server would give anyway. A
  // failed read leaves the URL tab open and names the purpose by its fallback
  // label; the 503 from the import itself is shown below, so no error row
  // is added for a hint that is not load-bearing.
  const { data: purposes } = useAiPurposes();
  const recipesPurpose = purposes?.find((p) => p.key === RECIPES_PURPOSE_KEY);
  const urlNeedsAi = recipesPurpose ? !recipesPurpose.usable : false;

  const purposeLabel = () =>
    recipesPurpose
      ? t(recipesPurpose.label_key, {
          defaultValue: recipesPurpose.key,
        })
      : t("recipes:ai.purposeLabel");

  const handleImport = async () => {
    setImportError(null);
    try {
      let preview: RecipeImportPreview;
      if (importMode === "url") {
        const trimmedUrl = importUrl.trim();
        if (!trimmedUrl) return;
        if (!/^https?:\/\//i.test(trimmedUrl)) {
          setImportError(t("recipes:import_export.invalid_url"));
          return;
        }
        preview = await previewMutation.mutateAsync({
          format: "url",
          url: trimmedUrl,
        });
      } else {
        if (!importJson.trim()) return;
        let parsed: Record<string, unknown>;
        try {
          parsed = JSON.parse(importJson) as Record<string, unknown>;
        } catch {
          setImportError(t("recipes:import_export.invalid_json"));
          return;
        }
        preview = await previewMutation.mutateAsync({
          format: "json",
          data: parsed,
        });
      }
      setImportPreview(preview);
      setModalOpen(false);
    } catch (err) {
      if (extractApiErrorCode(err) === "LLM_PURPOSE_UNBOUND") {
        // Race fallback: the binding vanished after the modal opened. The
        // purpose is named by its registry label, not its key, and the
        // message carries a single prefix.
        setImportError(
          t("recipes:import_export.import_error_ai_not_configured", {
            purpose: purposeLabel(),
          }),
        );
        return;
      }
      const reason = extractApiError(
        err,
        t("recipes:import_export.import_error_unknown"),
      );
      setImportError(
        t("recipes:import_export.import_error", { error: reason }),
      );
    }
  };

  const handleReviewSave = async (data: RecipeCreateInput) => {
    setSaveError(null);
    try {
      const recipe = await createMutation.mutateAsync(data);
      toast.success(
        t("recipes:import_export.import_success", { name: recipe.name }),
      );
      setImportPreview(null);
      setImportUrl("");
      setImportJson("");
      onImported(recipe);
    } catch (err) {
      setSaveError(extractApiError(err, t("recipes:errors.save_failed")));
    }
  };

  // Pasted text is the only copy of the reader's work in this tab, so the
  // example goes in unasked only over an empty field.
  const handleShowImportExample = () => {
    if (importJson.trim()) {
      setAskReplaceWithExample(true);
      return;
    }
    insertImportExample();
  };

  const insertImportExample = () => {
    setImportJson(
      JSON.stringify(
        {
          name: "Example Recipe",
          description: "A sample recipe showing the import format",
          instructions: "Mix all ingredients and bake at 180°C.",
          servings: 4,
          prep_time_minutes: 30,
          tags: ["example"],
          ingredients: [
            { name: "Flour", quantity: 300, uom: "g" },
            { name: "Eggs", quantity: 2, uom: "pcs" },
            { name: "Milk", quantity: 0.5, uom: "l" },
          ],
        },
        null,
        2,
      ),
    );
  };

  return (
    <>
      <ConfirmDialog
        open={askReplaceWithExample}
        title={t("recipes:import_export.example_replace_title")}
        message={t("recipes:import_export.example_replace_message")}
        confirmLabel={t("recipes:import_export.example_replace_confirm")}
        cancelLabel={t("common:form.cancel")}
        onConfirm={() => {
          insertImportExample();
          setAskReplaceWithExample(false);
        }}
        onCancel={() => setAskReplaceWithExample(false)}
      />
      <ImportModal
        isOpen={modalOpen}
        importMode={importMode}
        importUrl={importUrl}
        importJson={importJson}
        isPreviewPending={previewMutation.isPending}
        onModeChange={setImportMode}
        onUrlChange={setImportUrl}
        onJsonChange={setImportJson}
        onShowExample={handleShowImportExample}
        onImport={handleImport}
        onClose={() => {
          setModalOpen(false);
          onClose();
        }}
        titleText={t("recipes:import_export.import_title")}
        urlTabText={t("recipes:import_export.import_from_url")}
        jsonTabText={t("recipes:import_export.import_from_json")}
        urlLabel={t("recipes:import_export.import_url_label")}
        jsonLabel={t("recipes:import_export.import_json_label")}
        urlPlaceholder={t("recipes:import_export.import_url_placeholder")}
        jsonPlaceholder={t("recipes:import_export.import_json_placeholder")}
        showExampleText={t("recipes:import_export.show_example")}
        cancelText={t("common:form.cancel")}
        submitText={t("recipes:import_export.import_submit")}
        parsingText={t("recipes:import_export.review_parsing")}
        errorText={importError}
        urlNeedsAi={urlNeedsAi}
        urlNeedsAiNotice={t("recipes:import_export.ai_connection_required", {
          purpose: purposeLabel(),
        })}
        urlNeedsAiCtaText={t("recipes:import_export.set_up_ai_connection")}
      />

      {importPreview && (
        <ImportReviewModal
          preview={importPreview}
          onSave={handleReviewSave}
          onBack={() => {
            setImportPreview(null);
            setModalOpen(true);
          }}
          isSaving={createMutation.isPending}
          saveError={saveError}
        />
      )}
    </>
  );
}
