import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { itemsApi } from "@/lib/api/items";
import { getEveryPage } from "@/module-sdk";
import { queryKeys } from "@/hooks/queries/keys";
import type { ItemImportOutcome } from "@/components/import/types";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { ImportWizardSheet } from "@/components/import/ImportWizardSheet";
import type { MappingField } from "@/components/import/types";
import { useImportItems } from "@/modules/inventory/hooks/useItemMutations";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import type { LabelMatchMode } from "@/lib/api/items";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";
import type {
  CategoryDTO,
  FieldDefinition,
  StorageLocationSummary,
} from "@/types";
import {
  applyGrocyPreset,
  locationFieldKey,
  suggestMapping,
} from "./importMapping";

interface Props {
  onClose: () => void;
}

/** Column keys the importer understands, in the order they are offered. */
const MAPPING_FIELDS: { key: string; labelKey: string; required?: boolean }[] =
  [
    { key: "name", labelKey: "items:import.fields.name", required: true },
    { key: "quantity", labelKey: "items:import.fields.quantity" },
    { key: "unit", labelKey: "items:import.fields.unit" },
    { key: "expiry_date", labelKey: "items:import.fields.expiryDate" },
    { key: "freeze_date", labelKey: "items:import.fields.freezeDate" },
    {
      key: "location",
      labelKey: "items:import.fields.storageLocation",
    },
    { key: "category", labelKey: "items:import.fields.category" },
    { key: "brand", labelKey: "items:import.fields.brand" },
    { key: "barcode", labelKey: "items:import.fields.barcode" },
    { key: "serial_number", labelKey: "items:import.fields.serialNumber" },
    { key: "purchase_price", labelKey: "items:import.fields.purchasePrice" },
    { key: "label_code", labelKey: "items:import.fields.labelCode" },
  ];

/**
 * The product fields any location or category sets, once per key. A field set
 * on a warehouse applies to every shelf inside it, and one set on a category
 * to every product filed under it; the importer fills it for each row whose
 * location or category has it. Money and file fields stay out: a cell has no
 * currency or upload to give them, and so do the platform's own fields, which
 * have columns of their own.
 */
function productFields(
  storages: StorageLocationSummary[] | undefined,
  categories: CategoryDTO[] | undefined,
): FieldDefinition[] {
  const byKey = new Map<string, FieldDefinition>();
  const offer = (f: FieldDefinition) => {
    if (f.type === "money" || f.type === "file" || f.is_system) return;
    if (!byKey.has(f.key)) byKey.set(f.key, f);
  };
  (storages ?? []).forEach((s) => (s.field_definitions ?? []).forEach(offer));
  (categories ?? []).forEach((c) =>
    ((c.field_definitions ?? []) as FieldDefinition[]).forEach(offer),
  );
  return [...byKey.values()];
}

/**
 * The categories that ask for a money or file field. A cell carries neither,
 * so a row of such a category is refused whatever the file holds — said
 * before the import runs, not after every row of it has failed.
 */
function categoriesNeedingUncarriableFields(
  categories: CategoryDTO[] | undefined,
): { categories: string[]; fields: string[] } {
  const names = new Set<string>();
  const fields = new Set<string>();
  (categories ?? []).forEach((c) =>
    ((c.field_definitions ?? []) as FieldDefinition[]).forEach((f) => {
      if (!f.required || f.is_system) return;
      if (f.type !== "money" && f.type !== "file") return;
      names.add(c.name);
      fields.add(f.label ?? f.key);
    }),
  );
  return { categories: [...names], fields: [...fields] };
}

/** What a row does when its Label Code names a product already here. */
const LABEL_MATCH_MODES: LabelMatchMode[] = ["add", "skip", "overwrite"];

export default function ImportModal({ onClose }: Props) {
  const { t } = useTranslation(["common", "items", "inventory"]);
  const importMutation = useImportItems();
  // The backend gates founding locations on locations:write and founding
  // categories on categories:write, so the two flags are two toggles, each
  // shown only to an account that holds the key it spends. One switch wired
  // to both flags left an account holding just one of the keys no setting
  // under which its permission worked. A hidden toggle is not an ignored
  // one: its flag posts false, and the backend's own gate stays the
  // authority when a session outlives a role change.
  const canWriteCategories = useCanWrite("categories");
  const canWriteStorages = useCanWrite("locations");
  const [createCategories, setCreateCategories] = useState(true);
  const [createLocations, setCreateLocations] = useState(true);
  const [onLabelMatch, setOnLabelMatch] = useState<LabelMatchMode>("add");

  // The price feeds the stock value; where that value is not shown, the
  // item form drops the field, and the import neither offers the column nor
  // sends it — the header suggestion would otherwise map it unseen.
  const showInventoryValue = useShowInventoryValue();
  const offered = showInventoryValue
    ? MAPPING_FIELDS
    : MAPPING_FIELDS.filter((f) => f.key !== "purchase_price");

  // The product fields the locations and categories set become columns of the
  // mapping, so
  // this dialog — and only this dialog, once opened — reads them all. The
  // counts are not asked for: nothing here prints a number.
  const {
    data: storages,
    error: fieldsError,
    refetch: refetchFields,
  } = useQuery({
    queryKey: [...queryKeys.storages.all, "import-fields"],
    queryFn: () =>
      getEveryPage<StorageLocationSummary>("/locations", {
        counts: false,
        with_fields: true,
      }),
    staleTime: 60_000,
  });
  const {
    scoped: categories,
    error: categoriesError,
    refetch: refetchCategories,
  } = useScopedCategories();
  const ownFields = productFields(storages, categories);
  const unsupported = categoriesNeedingUncarriableFields(categories);
  const fields: MappingField[] = [
    ...offered.map((f) => ({
      key: f.key,
      label: t(f.labelKey),
      required: f.required,
    })),
    // A user's field keeps the words its label was given.
    ...ownFields.map((f) => ({
      key: locationFieldKey(f.key),
      label: f.label ?? f.key,
    })),
  ];

  /** The first line a reader sees. It names what the file did: the products
   *  it made, the records it added to products that were already there, and in
   *  the overwrite mode the rows it overwrote — "Added 2 products" over a row
   *  that was stock of a product the shop had called a new product one. */
  const summary = (result: ItemImportOutcome) => {
    const madeProducts = result.imported - result.joined_existing;
    const parts = [
      result.updated > 0
        ? t("items:import.matchedUpdated", { count: result.updated })
        : null,
      madeProducts > 0
        ? t("items:import.added", { count: madeProducts })
        : null,
      result.joined_existing > 0
        ? t("items:import.addedToExisting", { count: result.joined_existing })
        : null,
    ].filter(Boolean);
    return parts.length > 0
      ? parts.join(" · ")
      : t("items:import.added", { count: 0 });
  };

  return (
    <ImportWizardSheet<ItemImportOutcome>
      onClose={onClose}
      title={t("items:import.title")}
      formats={t("items:import.formats")}
      fields={fields}
      requiredField="name"
      // Without the category answer the mapping lacks their fields and the
      // warning about the ones a cell cannot fill is silent: a gap is not
      // "no categories", and processing would fail every row of them.
      canRun={categories !== undefined}
      analyze={(file) => itemsApi.analyzeImport(file)}
      suggest={(headers) =>
        suggestMapping(
          headers,
          ownFields,
          Object.fromEntries(offered.map((f) => [f.key, t(f.labelKey)])),
        )
      }
      run={(file, mapping) =>
        importMutation.mutateAsync({
          file,
          mapping: showInventoryValue
            ? mapping
            : { ...mapping, purchase_price: "" },
          createLocations: canWriteStorages && createLocations,
          createCategories: canWriteCategories && createCategories,
          onLabelMatch,
        })
      }
      texts={{
        analyzeFailed: t("inventory:toasts.importFailedToAnalyze"),
        importFailed: t("inventory:toasts.importFailed"),
        wait: t("items:import.pleaseWait"),
        added: (count) => t("items:import.added", { count }),
        summary,
        closeAndView: t("items:import.closeAndView"),
      }}
      secondaryUpload={{
        label: t("items:import.grocy"),
        hint: t("items:import.grocyHint"),
      }}
      mappingHeaderExtras={({ headers, mapping, setMapping }) => (
        <Button
          size="content"
          variant="ghost"
          onClick={() => {
            setMapping(applyGrocyPreset(headers, mapping));
            toast.success(t("inventory:toasts.importGrocyMappingApplied"));
          }}
          className="text-[10px] font-medium text-primary-600 hover:text-primary-700 uppercase tracking-wider bg-primary-50 px-3 py-1.5 rounded-lg border border-primary-100"
        >
          {t("items:import.applyGrocyPreset")}
        </Button>
      )}
      mappingExtras={({ mapping, filledCounts }) => (
        <>
          {/* Without the answer the columns the locations add are missing
              from the mapping, and a column of the file that belongs to one
              would be left out of the import without a word. */}
          {fieldsError && (
            <InlineQueryError
              className="px-2"
              error={fieldsError}
              onRetry={() => void refetchFields()}
            />
          )}
          {categoriesError != null && (
            <InlineQueryError
              className="px-2"
              error={categoriesError}
              onRetry={refetchCategories}
            />
          )}
          {unsupported.categories.length > 0 && (
            <p
              role="note"
              className="px-2 text-sm text-amber-700 dark:text-amber-400"
            >
              {t("items:import.unsupportedRequiredFields", {
                categories: unsupported.categories.join(", "),
                fields: unsupported.fields.join(", "),
              })}
            </p>
          )}
          {/* What the import will and will not do to what is already there. */}
          <div className="px-2">
            <ChoiceGroup
              label={t("items:import.labelMatch.label")}
              hint={t("items:import.labelMatch.hint")}
              layout="grid"
              options={LABEL_MATCH_MODES.map((mode) => ({
                id: mode,
                label: t(`items:import.labelMatch.modes.${mode}`),
              }))}
              value={onLabelMatch}
              onChange={(mode) => setOnLabelMatch(mode as LabelMatchMode)}
            />
            <p className="mt-2 text-sm text-on-secondary">
              {t(`items:import.labelMatch.notes.${onLabelMatch}`)}
            </p>
            {onLabelMatch !== "add" && !mapping.label_code && (
              /* Without the column there is nothing to match on, so every
                 row would quietly become a new product again. */
              <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
                {t("items:import.labelMatch.needsColumn")}
              </p>
            )}
            {onLabelMatch !== "add" &&
              mapping.label_code &&
              !(filledCounts[mapping.label_code as string] > 0) && (
                /* The column is mapped but not one row of the whole
                   file carries a code — the count the analysis made over
                   every row, not the five the preview shows, because
                   codes can start below them. Codes exist only once a
                   label has been printed, so an export-reimport round
                   trip walks in without any; the mode would then add
                   duplicates exactly as "add" does, which the person
                   deserves to know before the summary says so. */
                <p className="mt-2 text-sm text-amber-700 dark:text-amber-400">
                  {t("items:import.labelMatch.noCodesInFile")}
                </p>
              )}
          </div>
          <div className="px-2 space-y-3">
            {canWriteStorages && (
              <Checkbox
                checked={createLocations}
                onChange={(e) => setCreateLocations(e.target.checked)}
                className="w-5 h-5 rounded-lg"
                label={
                  <span className="text-sm font-semibold text-on-secondary group-hover:text-primary-600 transition-colors">
                    {t("items:import.autoCreateLocations")}
                  </span>
                }
              />
            )}
            {canWriteCategories && (
              <Checkbox
                checked={createCategories}
                onChange={(e) => setCreateCategories(e.target.checked)}
                className="w-5 h-5 rounded-lg"
                label={
                  <span className="text-sm font-semibold text-on-secondary group-hover:text-primary-600 transition-colors">
                    {t("items:import.autoCreateCategories")}
                  </span>
                }
              />
            )}
          </div>
        </>
      )}
      resultExtras={(result) =>
        result.skipped > 0 ||
        result.created_locations.length > 0 ||
        result.created_categories.length > 0 ? (
          /* What the file founded beside the products, and what it left
             alone, so the reader learns it here and not from new tiles in
             the storage tree. The updated count is on the first line now. */
          <div className="bg-surface p-6 rounded-xl border border-border text-left max-w-md mx-auto space-y-3">
            {result.skipped > 0 && (
              /* The count the shared stats grid does not carry: what the
                 Label Code matched and the mode left alone. */
              <p className="text-xs text-on">
                {t("items:import.matchedSkipped", { count: result.skipped })}
              </p>
            )}
            {result.created_locations.length > 0 && (
              <div>
                <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mb-1">
                  {t("items:import.foundedLocations", {
                    count: result.created_locations.length,
                  })}
                </p>
                <ul className="text-xs text-on space-y-0.5">
                  {result.created_locations.map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              </div>
            )}
            {result.created_categories.length > 0 && (
              <div>
                <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest mb-1">
                  {t("items:import.foundedCategories", {
                    count: result.created_categories.length,
                  })}
                </p>
                <ul className="text-xs text-on space-y-0.5">
                  {result.created_categories.map((name) => (
                    <li key={name}>{name}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ) : null
      }
    />
  );
}
