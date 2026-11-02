import type { MutableRefObject } from "react";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import FieldBuilder, {
  type FieldBuilderCommit,
} from "@/components/ui/FieldBuilder";
import { StorageTrackingFields } from "@/modules/spaces/components/StorageTrackingFields";
import { LocationTargetPicker } from "./LocationTargetPicker";
import { StorageQrCodeField } from "./StorageQrCodeField";
import type { StorageEditFormData } from "@/modules/spaces/hooks/useStorageEditForm";
import type { StorageLocationSummary, StorageType } from "@/types";

interface StorageEditFieldsProps {
  formData: StorageEditFormData;
  setFormData: (data: StorageEditFormData) => void;
  /** Lets the form settle a field the reader left half-typed when it saves. */
  fieldBuilderRef?: MutableRefObject<FieldBuilderCommit | null>;
  storageTypes: StorageType[];
  /** Set when the types never arrived: the picker gives way to a retry. */
  typesError?: unknown;
  onRetryTypes?: () => void;
  /** The location being edited: it and everything inside it are not places
   *  it may go. */
  locationId: string;
  isGeneratingCode: boolean;
  onGenerateCode: () => void;
  onQrDownload: () => void;
  /** The product fields the levels above set; they apply here as well. */
  inherited?: Pick<
    StorageLocationSummary,
    "inherited_context_schema" | "inherited_field_definitions"
  >;
  /** How many locations stand inside this one — its fields reach them all. */
  insideCount: number;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

/**
 * Every setting of a location, in the sections the page shows them in.
 *
 * The fields were the Edit dialog's body before; the dialog is gone and the
 * same controls now sit on the page under one Save. Tracked and custom
 * product fields used to appear only on a leaf — a location that holds both
 * locations and products of its own had no way to say what a product placed
 * directly there records. Every level edits them now.
 */
export function StorageEditFields({
  formData,
  setFormData,
  fieldBuilderRef,
  storageTypes,
  typesError,
  onRetryTypes,
  locationId,
  isGeneratingCode,
  onGenerateCode,
  onQrDownload,
  inherited,
  insideCount,
  t,
}: StorageEditFieldsProps) {
  const inheritedCustom = inherited?.inherited_field_definitions ?? [];

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <h3 className="text-sm font-semibold text-on">
          {t("locations:settings.basic")}
        </h3>
        <Input
          label={t("locations:edit.nameLabel")}
          type="text"
          value={formData.name}
          onChange={(event) =>
            setFormData({ ...formData, name: event.target.value })
          }
          className="text-base"
        />

        <div>
          <label
            htmlFor="edit-storage-type"
            className="mb-1.5 block text-[10px] font-medium uppercase tracking-widest text-on-muted"
          >
            {t("locations:onboarding.storageTypeLabel")}
          </label>
          {typesError ? (
            <InlineQueryError error={typesError} onRetry={onRetryTypes} />
          ) : (
            <NativeSelect
              id="edit-storage-type"
              value={formData.location_type_id ?? ""}
              onChange={(event) =>
                setFormData({
                  ...formData,
                  location_type_id: event.target.value || null,
                })
              }
              className="w-full"
            >
              <option value="">
                {t("locations:onboarding.storageTypeNone")}
              </option>
              {storageTypes.map((type) => (
                <option key={type.id} value={type.id}>
                  {type.name}
                </option>
              ))}
            </NativeSelect>
          )}
        </div>

        {/* "Lies in" — the move with everything inside, on every level. The
            picker leaves out this location and its whole subtree, because a
            move into itself is not a move. */}
        <LocationTargetPicker
          label={t("locations:settings.liesIn")}
          labelClassName="mb-1.5 ml-0 block text-[10px] font-medium uppercase tracking-widest text-on-muted"
          excludeSubtreeOf={[locationId]}
          value={formData.parent_id ?? ""}
          onChange={(id) =>
            setFormData({ ...formData, parent_id: id === "" ? null : id })
          }
          clearable
          clearLabel={t("locations:edit.noParentStorage")}
          placeholder={t("locations:edit.noParentStorage")}
          searchPlaceholder={t("common:search")}
          emptyMessage={t("common:noResults")}
          title={t("locations:settings.liesIn")}
        />

        <div>
          <label
            htmlFor="edit-storage-description"
            className="mb-1.5 block text-[10px] font-medium uppercase tracking-widest text-on-muted"
          >
            {t("locations:onboarding.descriptionLabel")}
          </label>
          <Input
            id="edit-storage-description"
            type="text"
            value={formData.description}
            onChange={(event) =>
              setFormData({ ...formData, description: event.target.value })
            }
            placeholder={t("locations:onboarding.descriptionPlaceholder")}
          />
        </div>

        {/* Named for the storage's own whereabouts: where a product sits
            inside it is the tracked "Shelf / position" field. */}
        <div>
          <label
            htmlFor="edit-storage-location-details"
            className="mb-1.5 block text-[10px] font-medium uppercase tracking-widest text-on-muted"
          >
            {t("locations:form.location")}
          </label>
          <Input
            id="edit-storage-location-details"
            type="text"
            value={formData.location_details}
            onChange={(event) =>
              setFormData({ ...formData, location_details: event.target.value })
            }
            placeholder={t("locations:form.locationPlaceholder")}
          />
        </div>

        {/* Walk order is not edited here any more: it belongs to the shelf's
            warehouse settings, set in Warehouse → Location settings
            together with the mix and the limits. The form still carries the
            value it was opened with, so saving this dialog leaves the order
            exactly as it was. */}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-on">
          {t("locations:settings.warehouse")}
        </h3>
        <Checkbox
          id="edit-storage-reserve"
          checked={formData.is_reserve}
          onChange={(event) =>
            setFormData({ ...formData, is_reserve: event.target.checked })
          }
          label={t("locations:settings.reserve")}
        />
        <p className="text-xs text-on-muted">
          {t("locations:settings.reserveHint")}
        </p>
      </section>

      <section className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-on">
            {t("locations:settings.productFields")}
          </h3>
          <p className="mt-0.5 text-xs text-on-muted">
            {t("locations:settings.productFieldsHint")}{" "}
            {insideCount > 0
              ? t("locations:settings.appliesInside", { count: insideCount })
              : t("locations:settings.appliesHere")}
          </p>
        </div>
        <div>
          <p className="mb-2 block text-[10px] font-medium uppercase tracking-widest text-on-muted">
            {t("locations:edit.trackedFields")}
          </p>
          <StorageTrackingFields
            value={formData.context_schema}
            onChange={(next) =>
              setFormData({ ...formData, context_schema: next })
            }
            t={t}
            variant="solid"
            inherited={inherited?.inherited_context_schema}
          />
        </div>
        <div>
          <p className="mb-2 block text-[10px] font-medium uppercase tracking-widest text-on-muted">
            {t("locations:edit.customFields")}
          </p>
          {/* Read-only: a level below adds fields, it cannot drop one that
              a level above set — that is changed where it was set. */}
          {inheritedCustom.length > 0 && (
            <ul
              aria-label={t("locations:settings.inheritedFields")}
              className="mb-2 space-y-1.5"
            >
              {inheritedCustom.map((field) => (
                <li
                  key={field.key}
                  className="flex min-h-10 items-center justify-between gap-3 rounded-xl border border-border bg-surface-inset px-3 py-2 text-sm"
                >
                  <span className="font-semibold text-on">
                    {field.label || field.key}
                  </span>
                  <span className="text-xs text-on-muted">
                    {t("locations:settings.inheritedFrom", {
                      name: field.from_name,
                    })}
                  </span>
                </li>
              ))}
            </ul>
          )}
          <FieldBuilder
            commitRef={fieldBuilderRef}
            fields={formData.field_definitions}
            onChange={(fields) =>
              setFormData({ ...formData, field_definitions: fields })
            }
          />
        </div>
      </section>

      <section className="space-y-4">
        <h3 className="text-sm font-semibold text-on">
          {t("locations:settings.labelAndCode")}
        </h3>
        <StorageQrCodeField
          shortCode={formData.short_code}
          onShortCodeChange={(value) =>
            setFormData({ ...formData, short_code: value })
          }
          labelShowDescription={formData.label_show_description}
          onLabelShowDescriptionChange={(checked) =>
            setFormData({ ...formData, label_show_description: checked })
          }
          isGeneratingCode={isGeneratingCode}
          onGenerateCode={onGenerateCode}
          onQrDownload={onQrDownload}
        />
      </section>
    </div>
  );
}
