import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, X, Loader2, Info, Check } from "lucide-react";
import { toast } from "sonner";
import FieldBuilder, {
  useFieldBuilderCommit,
} from "@/components/ui/FieldBuilder";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { CategoryAvatar } from "@/components/ui/CategoryAvatar";
import { EmojiPicker } from "@/components/ui/EmojiPicker";
import { ColorSwatchPicker } from "@/components/ui/ColorSwatchPicker";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { Sheet } from "@/components/ui/Sheet";
import { useActiveProfile } from "@/hooks/useActiveProfile";
import { categoryGroupLabel } from "@/modules/inventory/utils/categoryGroups";
import { RemovalStrategyChoice } from "./RemovalStrategyChoice";
import type { CategoryDTO, FieldDefinition } from "@/types";
import {
  useCreateCategory,
  useUpdateCategory,
} from "@/modules/shared/hooks/useCategories";

interface CategoryFormModalProps {
  isOpen: boolean;
  editingCategory: CategoryDTO | null;
  onClose: () => void;
  /**
   * A copy variant switch, not a context picker. It changes the form's
   * wording (name placeholder, emoji hints, fields-section title) and is
   * stamped as `context_tag` on create. Nothing here lets the user choose a
   * context — grouping the user controls lives in `group_label` below.
   */
  contextTag?: string;
  /**
   * Group labels already used in the organisation, offered as suggestions in
   * the "Group" combobox. Suggesting existing values is the only
   * thing keeping "Narzędzia", "narzedzia" and "Tools" out of one database.
   */
  groupSuggestions?: string[];
}

/**
 * The example inside the name field.
 *
 * "e.g. Dairy, Drinks..." on a workspace that tracks server racks names a
 * vertical the reader did not choose. The storage wizard's suggestions have
 * followed the product profile since they were written; so does this.
 */
function useCategoryNamePlaceholder(contextTag: string | undefined): string {
  const { t } = useTranslation(["categories"]);
  const profileKey = useActiveProfile()?.seed_profile ?? null;
  if (contextTag) return t("modal.namePlaceholderGeneric");
  if (!profileKey) return t("modal.namePlaceholder");
  return t(`modal.namePlaceholderProfiles.${profileKey}`, {
    defaultValue: t("modal.namePlaceholder"),
  });
}

interface CategoryFormData {
  name: string;
  group_label: string;
  emoji: string | null;
  color: string | null;
  field_definitions: FieldDefinition[];
  default_removal_strategy: CategoryDTO["default_removal_strategy"];
}

/** The form as it opens: the category being edited, or an empty one. */
function initialFormData(
  editingCategory: CategoryDTO | null,
): CategoryFormData {
  return {
    name: editingCategory?.name ?? "",
    group_label: editingCategory?.group_label ?? "",
    emoji: (editingCategory?.emoji ?? null) as string | null,
    color: (editingCategory?.color ?? null) as string | null,
    field_definitions: (editingCategory?.field_definitions ??
      []) as FieldDefinition[],
    default_removal_strategy: editingCategory?.default_removal_strategy ?? null,
  };
}

/** What the form sends for a category. */
function categoryPayload(
  formData: CategoryFormData,
  editingCategory: CategoryDTO | null,
  contextTag: string | undefined,
): Partial<CategoryDTO> {
  // Strip the legacy 'icon' field — slice 3 stopped writing it, and
  // slice 5 (cleanup migration) will drop the column. The backend
  // already accepts a missing icon (it is nullable).
  const groupLabel = formData.group_label.trim();
  const payload: Partial<CategoryDTO> = {
    name: formData.name,
    emoji: formData.emoji,
    color: formData.color,
    field_definitions: formData.field_definitions,
  };
  // Equipment categories do not ask (see the form), so they do not send it.
  if (!contextTag) {
    payload.default_removal_strategy = formData.default_removal_strategy;
  }
  // No group is a valid state, not missing data: an empty field is left
  // out of the payload (never sent as ""), unless it clears a group the
  // category had — then it goes as an explicit null.
  if (groupLabel) {
    payload.group_label = groupLabel;
  } else if (editingCategory?.group_label) {
    payload.group_label = null;
  }
  return payload;
}

export function CategoryFormModal({
  isOpen,
  editingCategory,
  onClose,
  contextTag,
  groupSuggestions = [],
}: CategoryFormModalProps) {
  const { t } = useTranslation(["categories", "common"]);
  const titleId = useId();
  const namePlaceholder = useCategoryNamePlaceholder(contextTag);

  const [formData, setFormData] = useState<CategoryFormData>(() =>
    initialFormData(editingCategory),
  );

  const createCategoryMutation = useCreateCategory();
  const updateCategoryMutation = useUpdateCategory();

  const isPending =
    createCategoryMutation.isPending || updateCategoryMutation.isPending;

  const fieldBuilder = useFieldBuilderCommit(formData.field_definitions);

  const handleSave = () => {
    // A field typed into the builder and not confirmed with "Add field" is
    // part of what the reader is saving: it joins the list, or the save
    // waits for them to finish it.
    const fieldDefinitions = fieldBuilder.commit();
    if (!fieldDefinitions) return;
    const payload = categoryPayload(
      { ...formData, field_definitions: fieldDefinitions },
      editingCategory,
      contextTag,
    );
    if (editingCategory) {
      updateCategoryMutation.mutate(
        { id: editingCategory.id, data: payload },
        {
          onSuccess: () => {
            toast.success(t("messages.updated"));
            onClose();
          },
        },
      );
    } else {
      createCategoryMutation.mutate(
        { ...payload, ...(contextTag ? { context_tag: contextTag } : {}) },
        {
          onSuccess: () => {
            toast.success(t("messages.created"));
            onClose();
          },
        },
      );
    }
  };

  if (!isOpen && !editingCategory) return null;

  return (
    <Sheet
      open={isOpen}
      onClose={onClose}
      backdropOpacity={60}
      aria-labelledby={titleId}
    >
      <div className="flex items-center justify-between border-b p-5">
        <h2 className="font-semibold text-on" id={titleId}>
          {editingCategory ? t("modal.titleEdit") : t("modal.titleAdd")}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:actions.close")}
        >
          <X size={18} />
        </Button>
      </div>

      <div className="overflow-y-auto p-5 space-y-5 flex-1">
        {/* The label carries no star of its own: `Input` renders one and
            hides it from the accessibility tree, and the preview below reads
            this same string — which is how "Category Name *" ended up drawn
            inside the preview swatch. */}
        <Input
          label={t("modal.nameLabel")}
          type="text"
          required
          value={formData.name}
          onChange={(e) => setFormData({ ...formData, name: e.target.value })}
          placeholder={namePlaceholder}
        />

        {/* Group: a combobox over the labels the organisation already
            uses, with free-text entry for a new one. The suggestions are the
            point — they are the only thing keeping "Tools", "tools" and
            "Narzędzia" from becoming three groups in one database. Optional:
            no group is a valid state, not missing data. */}
        <SearchableCombobox
          label={t("modal.groupLabel")}
          value={formData.group_label}
          onChange={(group) => setFormData({ ...formData, group_label: group })}
          onCreateNew={(query) =>
            setFormData({ ...formData, group_label: query.trim() })
          }
          createLabel={t("modal.groupCreate")}
          placeholder={t("modal.groupPlaceholder")}
          searchPlaceholder={t("modal.groupSearchPlaceholder")}
          emptyMessage={t("modal.groupEmpty")}
          title={t("modal.groupLabel")}
          options={[
            { id: "", name: t("modal.groupNone") },
            // The current value is always an option — a freshly typed label
            // is not in the suggestions yet, and the trigger renders the
            // placeholder for a value it cannot find.
            // The stored value is the id; what the reader sees is its
            // translation, the same one the categories list shows. Offering
            // the raw value is how a Polish interface came to propose
            // "FREEZER", "FRIDGE" and "PANTRY".
            ...Array.from(
              new Set(
                [formData.group_label, ...groupSuggestions].filter(
                  (g): g is string => Boolean(g?.trim()),
                ),
              ),
            ).map((g) => ({ id: g, name: categoryGroupLabel(t, g) })),
          ]}
        />

        {/* Appearance: live preview + symbol + color (Category Visual
            Identity v2). Preview mirrors what lists render via
            CategoryAvatar, so the user edits the actual result. */}
        <div className="rounded-xl border border-border bg-surface p-4 space-y-4">
          <div className="flex items-center gap-3">
            <CategoryAvatar
              category={{
                emoji: formData.emoji,
                color: formData.color,
                name: formData.name,
                contextTag: contextTag ?? null,
              }}
              size="lg"
              shape="circle"
            />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-on">
                {formData.name || t("modal.nameLabel")}
              </p>
              <p className="text-xs text-on-secondary">
                {t("modal.appearancePreview", {
                  defaultValue: "Preview",
                })}
              </p>
            </div>
          </div>
          <div className="space-y-1.5">
            <p className="block text-xs font-medium uppercase tracking-wide text-on-secondary ml-1">
              {t("modal.symbolLabel", { defaultValue: "Symbol" })}
            </p>
            <EmojiPicker
              value={formData.emoji}
              onChange={(emoji) => setFormData({ ...formData, emoji })}
              contextTag={contextTag}
            />
          </div>
          <div className="space-y-1.5">
            <p className="block text-xs font-medium uppercase tracking-wide text-on-secondary ml-1">
              {t("modal.colorLabel", { defaultValue: "Color" })}
            </p>
            <ColorSwatchPicker
              value={formData.color}
              onChange={(color) => setFormData({ ...formData, color })}
            />
          </div>
        </div>

        {/* Assets are not drawn by date, so an equipment category does not
            ask the question. */}
        {!contextTag && (
          <RemovalStrategyChoice
            label={t("modal.removalStrategyLabel")}
            hint={t("modal.removalStrategyHint")}
            value={formData.default_removal_strategy}
            onChange={(strategy) =>
              setFormData({ ...formData, default_removal_strategy: strategy })
            }
          />
        )}

        <div className="border-t pt-5">
          {!contextTag && (
            <div className="flex items-center gap-2 mb-4 ml-1">
              <h3 className="text-xs font-medium uppercase tracking-wide text-on-secondary">
                {t("modal.fieldsTitle", {
                  defaultValue: "Fields for products in this category",
                })}
              </h3>
              <div className="group relative">
                <Info size={14} className="text-on-muted cursor-help" />
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-2 bg-gray-900 text-[10px] text-white rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10 shadow-md">
                  {t("modal.fieldsHelp", {
                    defaultValue:
                      "Define additional fields (e.g. 'Size', 'Capacity') that will appear in the add product form only after selecting this category.",
                  })}
                </div>
              </div>
            </div>
          )}
          <FieldBuilder
            commitRef={fieldBuilder.ref}
            fields={formData.field_definitions}
            onChange={(fields) =>
              setFormData({ ...formData, field_definitions: fields })
            }
            defaultOpen={Boolean(contextTag)}
            titleOverride={
              contextTag
                ? t("modal.fieldsEquipmentTitle", {
                    defaultValue: "Field Configuration",
                  })
                : undefined
            }
            subtitleOverride={
              contextTag && formData.field_definitions.length === 0
                ? t("modal.fieldsEquipmentEmptySubtitle", {
                    defaultValue:
                      "No predefined fields — this category starts empty. Add the fields its products should ask for.",
                  })
                : undefined
            }
          />
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 border-t bg-surface p-5">
        <Button variant="outline" onClick={onClose}>
          {t("actions.cancel", { ns: "common" })}
        </Button>
        <Button onClick={handleSave} disabled={!formData.name || isPending}>
          {isPending ? (
            <Loader2 size={20} className="animate-spin" />
          ) : editingCategory ? (
            <Check size={20} />
          ) : (
            <Plus size={20} />
          )}
          <span>{t("actions.save", { ns: "common" })}</span>
        </Button>
      </div>
    </Sheet>
  );
}
