import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { categoryLabel } from "@/lib/i18nHelpers";

import { ProductCombobox } from "@/components/ui/ProductCombobox";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import { useStorageTypes } from "@/modules/shared/hooks/useStorages";
import { documentsApi } from "@/modules/warehouse/api/documents";
import type { CatalogueSearchResult } from "@/modules/warehouse/api/documents";
import type { PutawayMatchForm } from "./putawayRuleForm";

interface PutawayMatchFieldsProps {
  form: PutawayMatchForm;
  set: <K extends keyof PutawayMatchForm>(
    key: K,
    value: PutawayMatchForm[K],
  ) => void;
  selectedTemplate: CatalogueSearchResult | null;
  onTemplateChange: (product: CatalogueSearchResult | null) => void;
}

/**
 * The four keys a putaway rule can match on, and the sentence they add up to.
 *
 * The resolver fires on ANY filled key and ranks the match by how specific it
 * is (product -> category -> category group -> storage type); `priority` only
 * breaks ties inside one tier. Four fields stacked in a column say none of
 * that — they read as a conjunction, which is how a rule meant for
 * dairy ends up catching everything headed for a freezer.
 */
export function PutawayMatchFields({
  form,
  set,
  selectedTemplate,
  onTemplateChange,
}: PutawayMatchFieldsProps) {
  const { t } = useTranslation("warehouse");
  // This dialog writes a rule the resolver fires on incoming goods, so both
  // the category and the category-group picker are *offers* on a general
  // screen: a rule written on a category the policy keeps off the lists
  // would never fire. `keepId` keeps the edited rule's own category
  // selectable (and named below) even when a module owns it.
  const { scoped: categories = [] } = useScopedCategories(form.category_id);
  const {
    data: storageTypes = [],
    isError: storageTypesFailed,
    error: storageTypesError,
    refetch: refetchStorageTypes,
  } = useStorageTypes();

  // both of these were free-text boxes over a closed set the server
  // already knows — it builds the same set in `_validate_match_keys`, but
  // only to reject what the user typed. The values are here anyway: the
  // dialog already loads the categories, and the storage types are one
  // cached query the rest of the app shares.
  const contextTagOptions = useMemo(() => {
    const byTag = new Map<string, string[]>();
    for (const category of categories) {
      if (!category.context_tag) continue;
      const names = byTag.get(category.context_tag) ?? [];
      names.push(categoryLabel(t, category.code, category.name));
      byTag.set(category.context_tag, names);
    }
    return [...byTag.entries()].map(([tag, names]) => ({
      id: tag,
      name: tag,
      // The tag is an identifier nothing in the app displays; the categories
      // standing behind it are what the user recognises.
      path: names.join(", "),
    }));
  }, [categories, t]);

  const storageTypeOptions = useMemo(
    // The engine matches on `type_code`; the user reads the name.
    () => storageTypes.map((type) => ({ id: type.type_code, name: type.name })),
    [storageTypes],
  );

  // the resolver fires on ANY filled key and ranks the match by how
  // specific it is (product → category → category group → storage type);
  // `priority` only breaks ties inside one tier. Four stacked fields say
  // none of that — they read as a conjunction. This is the same list in the
  // same order, turned into the sentence the user is actually writing.
  const matchConditions = useMemo(() => {
    const category = categories.find((c) => c.id === form.category_id);
    const storageType = storageTypes.find(
      (type) => type.type_code === form.location_type_code,
    );
    return [
      selectedTemplate?.name
        ? {
            label: t("putaway.fields.product_template", "Product"),
            value: selectedTemplate.name,
          }
        : null,
      category
        ? {
            label: t("putaway.fields.category", "Category"),
            value: categoryLabel(t, category.code, category.name),
          }
        : null,
      form.context_tag
        ? {
            label: t("putaway.fields.context_tag", "Category group"),
            value: form.context_tag,
          }
        : null,
      storageType
        ? {
            label: t("putaway.fields.location_type", "Storage type"),
            value: storageType.name,
          }
        : null,
    ].filter((condition): condition is { label: string; value: string } =>
      Boolean(condition),
    );
  }, [
    categories,
    storageTypes,
    selectedTemplate,
    form.category_id,
    form.context_tag,
    form.location_type_code,
    t,
  ]);

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
          {t("putaway.match.section", "Match conditions")}
        </p>
        <p className="mt-1 text-xs text-on-secondary">
          {t(
            "putaway.match.any_hint",
            "The rule fires when any one of these matches — not when all of them do.",
          )}
        </p>
      </div>

      <div className="space-y-1.5">
        <ProductCombobox
          value={selectedTemplate}
          onSelect={(product) => {
            onTemplateChange(product);
            set("product_template_id", product.product_template_id);
          }}
          onClear={() => {
            onTemplateChange(null);
            set("product_template_id", "");
          }}
          search={(q) => documentsApi.productSearch(q)}
          // The three conditions below say "Optional — …" in their empty
          // state; this one said "Search products", so the first field on the
          // dialog read as the one that had to be filled in.
          placeholder={t(
            "putaway.placeholders.product_template",
            "Optional — select product",
          )}
          // The dialog's other match fields label their comboboxes with a
          // sentence-case label in the field's own row; the shared combobox
          // gets the same labelClassName to sit in that row.
          label={t("putaway.fields.product_template", "Product")}
        />
      </div>

      <SearchableCombobox
        label={t("putaway.fields.category", "Category")}
        // Both pickers in this dialog defaulted to the name "Select",
        // leaving a screen reader no way to tell the category apart
        // from the location.
        title={t("putaway.fields.category", "Category")}
        options={categories.map((c) => ({
          id: c.id,
          name: categoryLabel(t, c.code, c.name),
        }))}
        value={form.category_id}
        onChange={(id) => set("category_id", id)}
        placeholder={t(
          "putaway.placeholders.category",
          "Optional — select category",
        )}
        searchPlaceholder={t("common:actions.search", "Search")}
      />

      {/* A picker with nothing in it is worse than no picker: it sends
              the user looking for a value the organization has not defined
              yet. Both fields stay away until there is something to pick —
              and a failed storage-type list says so instead of vanishing. */}
      {/* `grid-cols-1` is `minmax(0, 1fr)`: the bare implicit column is
          `auto`, which a selected group's list of category names stretched to
          its full line (849 px in a 334 px form on a phone). */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 items-end">
        {contextTagOptions.length > 0 && (
          <SearchableCombobox
            label={t("putaway.fields.context_tag", "Category group")}
            title={t("putaway.fields.context_tag", "Category group")}
            options={contextTagOptions}
            value={form.context_tag}
            onChange={(id) => set("context_tag", id)}
            placeholder={t(
              "putaway.placeholders.context_tag",
              "Optional — select category group",
            )}
            searchPlaceholder={t("common:actions.search", "Search")}
          />
        )}
        {storageTypesFailed && (
          <InlineQueryError
            error={storageTypesError}
            onRetry={() => void refetchStorageTypes()}
          />
        )}
        {storageTypeOptions.length > 0 && (
          <SearchableCombobox
            label={t("putaway.fields.location_type", "Storage type")}
            title={t("putaway.fields.location_type", "Storage type")}
            options={storageTypeOptions}
            value={form.location_type_code}
            onChange={(id) => set("location_type_code", id)}
            placeholder={t(
              "putaway.placeholders.location_type",
              "Optional — select storage type",
            )}
            searchPlaceholder={t("common:actions.search", "Search")}
          />
        )}
      </div>

      {matchConditions.length > 0 && (
        <p
          data-testid="putaway-match-summary"
          className="rounded-md bg-surface-inset/60 px-3 py-2 text-xs text-on-secondary"
        >
          {/* "fires for category group X" needs a genitive in pl/de/fr and
              the label is a nominative — a sentence assembled from field
              labels cannot decline. A colon list carries the same meaning
              and survives every language. */}
          {t("putaway.match.summary_prefix", "This rule fires when:")}{" "}
          {matchConditions
            .map((c) => `${c.label} = ${c.value}`)
            .join(` ${t("putaway.match.or", "or")} `)}
          {matchConditions.length > 1 && (
            <>
              {". "}
              {t(
                "putaway.match.specificity",
                "If more than one matches, the most specific wins: {{winner}}.",
                { winner: matchConditions[0].label },
              )}
            </>
          )}
        </p>
      )}
    </div>
  );
}
