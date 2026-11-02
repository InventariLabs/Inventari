import { Camera, ExternalLink, Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import type { FieldDefinition, CategoryDTO } from "@/types";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import UnifiedFieldRenderer from "../UnifiedFieldRenderer";
import type { TemplateUnitPrompt } from "@/modules/inventory/hooks/useItemForm";
import { LocationCombobox } from "@/module-sdk";

interface ProductFormContentProps {
  formData: Record<string, unknown>;
  onChange: (key: string, value: unknown, isMetadata?: boolean) => void;
  onFileSelect?: (fieldKey: string, file: File) => void;
  onImageSelect?: (file: File) => void | Promise<void>;
  errors: Record<string, string>;
  fieldDefinitions: FieldDefinition[];
  categories?: CategoryDTO[];
  onAddCategory?: () => void;
  imagePreview?: string | null;
  setImagePreview?: (url: string | null) => void;
  /**
   * The storage field's answer to "the picker has nothing to offer", rendered
   * under the control. Passed as an element (module boundaries: the spaces
   * module's StorageRequired is the caller's to import, not this form's).
   */
  storageGate?: ReactNode;
  /**
   * Opens the caller's "new location" sheet, with whatever the reader had
   * typed into the picker's search. Without it the picker offers existing
   * locations only.
   */
  onAddStorage?: (query: string) => void;
  /** The unit the matched product template keeps — the hint by the picker. */
  templateUnit?: TemplateUnitPrompt | null;
}

/**
 * The category picker, as the form renders it when nothing else declares one.
 *
 * A category is a Core concept — the app has a screen for it, a filter on the
 * list and a bulk edit that changes it. Its visibility is decided once, in
 * `SYSTEM_FIELDS` (with the category's own `field_definitions` as override),
 * so the field this form draws is the same definition the submission payload
 * is built from: a picker the form shows and a payload that drops the value
 * used to be two different answers to one choice.
 */
export default function ProductFormContent({
  formData,
  onChange,
  onFileSelect,
  onImageSelect,
  errors,
  fieldDefinitions,
  categories,
  onAddCategory,
  imagePreview,
  setImagePreview,
  storageGate,
  onAddStorage,
  templateUnit = null,
}: ProductFormContentProps) {
  const { t } = useTranslation(["items", "categories", "common"]);

  // The shortcut below the picker and the field itself have to agree on
  // whether anything is chosen.
  const storageValue = (formData.location_id as string) || "";
  const selectedStorageId = storageValue;

  // Define field groups for layout (Sync with ItemEditModal)
  const FIELD_GROUPS = {
    identity: ["brand", "category_id", "barcode", "sku"],
    inventory: ["shelf_location", "quantity", "unit", "weight"],
    dates: ["expiry_date", "freeze_date", "purchase_price", "description"],
    traceability: ["serial_number"],
  };

  // Flatten all handled keys
  const HANDLED_KEYS = [
    "name",
    "location_id",
    ...Object.values(FIELD_GROUPS).flat(),
  ];

  // SECTION 1: IDENTITY
  const identityFields = fieldDefinitions.filter((f) =>
    FIELD_GROUPS.identity.includes(f.key),
  );
  const hasVisibleIdentity = identityFields.some((f) => f.visible);

  // SECTION 2: LOCATION & INVENTORY
  const inventoryFields = fieldDefinitions.filter((f) =>
    FIELD_GROUPS.inventory.includes(f.key),
  );
  const hasVisibleInventory = inventoryFields.some((f) => f.visible);

  // SECTION 3: DATES & PRICES
  const dateFields = fieldDefinitions.filter((f) =>
    FIELD_GROUPS.dates.includes(f.key),
  );
  const hasVisibleDates = dateFields.some((f) => f.visible);

  // SECTION 4: CUSTOM / DYNAMIC FIELDS
  const customFields = fieldDefinitions.filter(
    (f) => !HANDLED_KEYS.includes(f.key),
  );
  const hasVisibleCustom = customFields.some((f) => f.visible);

  // SECTION 5: TRACEABILITY (SN / LOT)
  const traceabilityFields = fieldDefinitions.filter((f) =>
    FIELD_GROUPS.traceability.includes(f.key),
  );
  const hasVisibleTraceability = traceabilityFields.some((f) => f.visible);

  return (
    <div className="space-y-7">
      {/* Top Section - Image, Name & Storage (2 columns on desktop) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left Column - Image & Name */}
        <div className="space-y-5">
          <div className="flex gap-4 items-start">
            {setImagePreview && (
              <label className="w-24 h-24 rounded-xl border border-dashed border-border bg-surface flex flex-col items-center justify-center cursor-pointer hover:bg-primary-50 hover:border-primary-300 transition-all overflow-hidden shrink-0">
                {imagePreview ? (
                  <img
                    src={imagePreview}
                    className="w-full h-full object-cover"
                    alt={t("common:a11y.imagePreview")}
                    loading="lazy"
                  />
                ) : (
                  <Camera size={22} className="text-on-muted" />
                )}
                <input
                  type="file"
                  className="hidden"
                  accept="image/*"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      // The local preview bridges the wait for an upload;
                      // once the handler's promise settles it must not land
                      // over whatever the handler put on show.
                      let settled = false;
                      const reader = new FileReader();
                      reader.onloadend = () => {
                        if (!settled) setImagePreview(reader.result as string);
                      };
                      reader.readAsDataURL(file);
                      void onImageSelect?.(file)?.finally(() => {
                        settled = true;
                      });
                    }
                  }}
                />
              </label>
            )}
            <div className="flex-1">
              <Input
                id="name"
                label={t("itemName")}
                type="text"
                required
                value={formData.name as string}
                onChange={(e) => onChange("name", e.target.value)}
                placeholder={t("itemNamePlaceholder", {
                  defaultValue: "e.g. Multimeter DT-9205A",
                })}
                error={errors.name}
              />
            </div>
          </div>
        </div>

        {/* Right Column - Storage */}
        <div className="flex flex-col justify-start">
          <LocationCombobox
            id="storage-combobox"
            label={t("itemStorage")}
            required
            // A product is put down: it is offered what may hold stock, never
            // a place a module owns — and the place it already stands in,
            // whatever owns it, so opening a record does not blank the field.
            scope={{ purpose: "stock" }}
            value={storageValue}
            onChange={(id) => onChange("location_id", id)}
            placeholder={t("selectStorage", {
              defaultValue: "Select storage",
            })}
            searchPlaceholder={t("common:search", {
              defaultValue: "Search...",
            })}
            emptyMessage={t("common:noResults")}
            title={t("itemStorage", { defaultValue: "Storage location" })}
            // A place that is not on the list is made here, not on the
            // Storages screen in another tab: the panel offers it for a
            // search that found nothing, and the button below at all times.
            onCreateNew={onAddStorage}
            createLabel={onAddStorage ? t("addStorage") : undefined}
          />
          {errors.location_id && (
            <p className="text-xs text-red-600 mt-1.5 font-medium">
              {errors.location_id}
            </p>
          )}
          {/* An empty picker used to cost the whole form: the page above was
              replaced by a panel that sent the reader to settings. The field
              keeps its place and the way forward sits under it. */}
          {storageGate && <div className="mt-1.5">{storageGate}</div>}
          {/* Below the control, not above it: a row of its own above the
              label started this column ~24px lower than the name field
              beside it, and the two never lined up. */}
          <div className="flex items-center justify-end gap-3 mt-1.5">
            {onAddStorage && (
              <Button
                type="button"
                variant="link"
                size="sm"
                onClick={() => onAddStorage("")}
                leftIcon={<Plus size={12} />}
                className="mr-auto px-0 gap-1 text-on-primary"
              >
                {t("addStorage")}
              </Button>
            )}
            <a
              href={
                selectedStorageId
                  ? // The link says "configure", so it opens the edit sheet.
                    // Without the parameter it landed on the location's
                    // product list and left one more click to guess.
                    `/inventory/locations/${selectedStorageId}?configure=true`
                  : "/inventory/locations"
              }
              target="_blank"
              rel="noopener noreferrer"
              // The link-text token: `primary-500` measured 2.53:1 on white
              // at 12px, where AA asks 4.5:1 in both themes.
              className="flex min-h-6 items-center gap-1 text-xs text-on-primary hover:underline"
              title={
                selectedStorageId
                  ? t("configureStorageTitle")
                  : t("manageStoragesTitle")
              }
            >
              <ExternalLink size={12} />
              {selectedStorageId ? t("configureStorage") : t("manageStorages")}
            </a>
          </div>
        </div>
      </div>

      {/* SECTION 1: IDENTITY */}
      {hasVisibleIdentity && (
        <div className="space-y-4">
          <h3 className="text-[10px] font-medium uppercase tracking-wider text-on-secondary">
            {t("identificationSection", {
              defaultValue: "Product Identification",
            })}
          </h3>
          <UnifiedFieldRenderer
            fieldDefinitions={identityFields}
            formData={formData}
            onChange={onChange}
            errors={errors}
            categories={categories}
            className="grid-cols-1 lg:grid-cols-2"
            onAddCategory={onAddCategory}
          />
        </div>
      )}

      {/* SECTION 2: LOCATION & INVENTORY */}
      {hasVisibleInventory && (
        <div className="space-y-4">
          <h3 className="text-[10px] font-medium uppercase tracking-wider text-on-secondary">
            {t("locationSection", { defaultValue: "Location & stock" })}
          </h3>
          <UnifiedFieldRenderer
            fieldDefinitions={inventoryFields}
            formData={formData}
            onChange={onChange}
            errors={errors}
            className="grid-cols-1 lg:grid-cols-2"
            templateUnit={templateUnit}
          />
        </div>
      )}

      {/* SECTION 3: DATES & PRICES */}
      {hasVisibleDates && (
        <div className="space-y-4">
          <h3 className="text-[10px] font-medium uppercase tracking-wider text-on-secondary">
            {t("quantityAndDates", { defaultValue: "Dates & details" })}
          </h3>
          <UnifiedFieldRenderer
            fieldDefinitions={dateFields}
            formData={formData}
            onChange={onChange}
            errors={errors}
            className="grid-cols-1 lg:grid-cols-2"
          />
        </div>
      )}

      {/* SECTION 4: CUSTOM / DYNAMIC FIELDS */}
      {hasVisibleCustom && (
        <div className="space-y-4">
          <h3 className="text-[10px] font-medium uppercase tracking-wider text-on-secondary">
            {t("common:additionalInfo")}
          </h3>
          <UnifiedFieldRenderer
            fieldDefinitions={customFields}
            formData={formData}
            onChange={onChange}
            onFileSelect={onFileSelect}
            errors={errors}
            className="grid-cols-1 lg:grid-cols-2"
          />
        </div>
      )}

      {/* SECTION 5: TRACEABILITY (SN / LOT) */}
      {hasVisibleTraceability && (
        <div className="space-y-4">
          <h3 className="text-[10px] font-medium uppercase tracking-wider text-on-secondary">
            {t("sections.traceability", { defaultValue: "Traceability" })}
          </h3>
          <UnifiedFieldRenderer
            fieldDefinitions={traceabilityFields}
            formData={formData}
            onChange={onChange}
            errors={errors}
            className="grid-cols-1 lg:grid-cols-2"
          />
        </div>
      )}
    </div>
  );
}
