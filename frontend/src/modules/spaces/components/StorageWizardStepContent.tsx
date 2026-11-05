/**
 * StepContent — renders the body of each StorageWizard step.
 * Extracted from StorageWizard.tsx to keep files focused.
 */
import type { MutableRefObject } from "react";
import { Check, ChevronDown, Barcode } from "lucide-react";
import { FieldDefinition, StorageType } from "@/types";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { LocationCombobox } from "@/module-sdk";
import { Textarea } from "@/components/ui/Textarea";
import FieldBuilder, {
  type FieldBuilderCommit,
} from "@/components/ui/FieldBuilder";
import {
  NEUTRAL_BASE_FIELD_ICONS,
  NEUTRAL_BASE_FIELDS_TOGGLEABLE,
  type NeutralBaseFieldKey,
} from "@/modules/spaces/utils/neutralBaseFields";

export type Step = 1 | 2 | 3;

// Local icon alias so JSX stays readable. The shared module already exports
// NEUTRAL_BASE_FIELD_ICONS — we just re-bind it under the legacy name used in
// the rest of the file. A later cleanup can remove this alias.
const FIELD_ICONS = NEUTRAL_BASE_FIELD_ICONS;

// Toggleable fields shown in step 3, in display order. Vertical-specific
// fields (freeze_date, expiry_date, etc.) come from the product's category.
const ALL_TRACKING_FIELDS = NEUTRAL_BASE_FIELDS_TOGGLEABLE;

export interface StepContentProps {
  step: Step;
  parentId: string | null;
  parentName: string;
  locationName: string;
  selectedFields: string[] | null;
  effectiveFields: string[];
  customFields: FieldDefinition[];
  /** Lets the wizard settle a field the reader left half-typed when it creates. */
  fieldBuilderRef?: MutableRefObject<FieldBuilderCommit | null>;
  /** Whether the organization has any place a new one could go under. */
  hasParents: boolean;
  filteredParentSuggestions: string[];
  locationSuggestions: string[];
  parentInputRef: React.RefObject<HTMLInputElement>;
  locationInputRef: React.RefObject<HTMLInputElement>;
  showAdvanced: boolean;
  labelCode: string;
  description: string;
  storageTypes: StorageType[];
  /** Set when the locations never arrived: the parent picker gives way to a retry. */
  parentsError?: unknown;
  onRetryParents?: () => void;
  /** Set when the types never arrived: the type picker gives way to a retry. */
  typesError?: unknown;
  onRetryTypes?: () => void;
  storageTypeId: string | null;
  onStorageTypeChange: (v: string) => void;
  onSelectParent: (id: string) => void;
  onParentChip: (name: string) => void;
  onParentNameChange: (v: string) => void;
  onLocationNameChange: (v: string) => void;
  onLocationChip: (name: string) => void;
  onFieldsChange: (fields: string[]) => void;
  onCustomFieldsChange: (fields: FieldDefinition[]) => void;
  onCustomize: () => void;
  onToggleAdvanced: () => void;
  onLabelCodeChange: (v: string) => void;
  onDescriptionChange: (v: string) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

export function StepContent({
  step,
  parentId,
  parentName,
  locationName,
  effectiveFields,
  customFields,
  fieldBuilderRef,
  hasParents,
  filteredParentSuggestions,
  locationSuggestions,
  parentInputRef,
  locationInputRef,
  showAdvanced,
  labelCode,
  description,
  storageTypes,
  parentsError,
  onRetryParents,
  typesError,
  onRetryTypes,
  storageTypeId,
  onStorageTypeChange,
  onSelectParent,
  onParentChip,
  onParentNameChange,
  onLocationNameChange,
  onLocationChip,
  onFieldsChange,
  onCustomFieldsChange,
  onCustomize,
  onToggleAdvanced,
  onLabelCodeChange,
  onDescriptionChange,
  t,
}: StepContentProps) {
  if (step === 1) {
    return (
      <div className="pb-4 space-y-5">
        <p className="text-sm text-on-secondary">
          {/* "your first storage" is true once. Said over an existing list of
              storages it reads as though the app forgot them. */}
          {hasParents
            ? t("locations:onboarding.step1DescMore")
            : t("locations:onboarding.step1Desc")}
        </p>

        {/* ADR-018: a chip row could only ever show one level of the tree.
            Every location is a possible parent now, so the choice is a picker
            — searchable, and each name carries the path that tells two
            shelves called "Top" apart. */}
        {parentsError ? (
          <InlineQueryError error={parentsError} onRetry={onRetryParents} />
        ) : null}
        {hasParents && (
          <LocationCombobox
            scope={{ purpose: "general" }}
            value={parentId ?? ""}
            onChange={onSelectParent}
            label={t("locations:onboarding.parentLabel")}
            title={t("locations:onboarding.parentLabel")}
            placeholder={t("locations:onboarding.parentPlaceholder")}
            searchPlaceholder={t("common:search")}
            emptyMessage={t("common:noResults")}
            // The wizard is a fullscreen surface; without this the panel opens
            // behind it and the list cannot be reached.
            layer="fullscreen"
          />
        )}

        <div>
          <p className="text-xs font-medium uppercase tracking-widest text-on-muted mb-2">
            {hasParents
              ? t("locations:onboarding.newLocation")
              : t("locations:onboarding.typeOrSelect")}
          </p>
          <Input
            ref={parentInputRef}
            type="text"
            aria-label={t("locations:onboarding.typeOrSelect")}
            value={parentName}
            onChange={(e) => onParentNameChange(e.target.value)}
            className="text-base"
            placeholder={t("locations:onboarding.step1Placeholder")}
          />
        </div>

        {filteredParentSuggestions.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {filteredParentSuggestions.map((s) => (
              <Button
                key={s}
                variant={
                  parentName === s && !parentId ? "secondary" : "outline"
                }
                size="sm"
                onClick={() => onParentChip(s)}
              >
                {s}
              </Button>
            ))}
          </div>
        )}
      </div>
    );
  }

  if (step === 2) {
    return (
      <div className="pb-4 space-y-5">
        <p className="text-sm text-on-secondary">
          {t("locations:onboarding.step2Desc")}
        </p>
        <Input
          ref={locationInputRef}
          type="text"
          aria-label={t("locations:onboarding.step2Desc")}
          value={locationName}
          onChange={(e) => onLocationNameChange(e.target.value)}
          className="text-base"
          placeholder={t("locations:onboarding.step2Placeholder")}
        />
        <div className="flex flex-wrap gap-2">
          {locationSuggestions.map((s) => (
            <Button
              key={s}
              variant={locationName === s ? "secondary" : "outline"}
              size="sm"
              onClick={() => onLocationChip(s)}
            >
              {s}
            </Button>
          ))}
        </div>

        {/* Tracking-fields preview — always shown when a name is typed */}
        {locationName.trim() && (
          <div className="p-3 rounded-2xl bg-primary-50 border border-primary-100 space-y-2">
            <p className="text-[10px] font-medium uppercase tracking-widest text-primary-400">
              {t("locations:onboarding.trackingFieldsLabel")}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {effectiveFields.map((key) => {
                // One label per field, shared with the storage editor —
                // the same box was "Barcode (EAN)" here and "Product code"
                // there, which reads as two different fields.
                const label = t(`locations:fieldLabels.${key}`, {
                  defaultValue: key,
                });
                const Icon = FIELD_ICONS[key as NeutralBaseFieldKey];
                return (
                  <span
                    key={key}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-surface-card border border-primary-200 text-xs font-medium text-primary-800"
                  >
                    {Icon && <Icon size={12} className="text-primary-500" />}
                    {label}
                  </span>
                );
              })}
              {effectiveFields.length === 0 && (
                <span className="text-xs text-primary-500">
                  {t("locations:onboarding.onlyLocation")}
                </span>
              )}
            </div>
            <div className="flex justify-end">
              <Button
                size="content"
                variant="link"
                onClick={onCustomize}
                className="text-primary-400 hover:text-primary-600 px-0 py-2 min-h-11 md:min-h-10 text-xs"
              >
                {t("locations:onboarding.customize")}
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  }

  // Step 3 — field checkboxes for custom tracking
  const toggleField = (key: string) => {
    const current = effectiveFields;
    const next = current.includes(key)
      ? current.filter((f) => f !== key)
      : [...current, key];
    onFieldsChange(next);
  };

  return (
    <div className="pb-4 space-y-5">
      <p className="text-sm text-on-secondary">
        {t("locations:onboarding.step3Desc")}
      </p>

      {/* The type seeds the tracking fields below it, and downstream it is
          what tells a screen this place holds food. Under "Advanced options"
          and empty by default, it was a classification nobody made — and the
          filters keyed on it silently passed everything through. */}
      <div>
        <label
          htmlFor="storage-type"
          className="block text-[10px] font-medium uppercase tracking-widest text-on-muted mb-1.5"
        >
          {t("locations:onboarding.storageTypeLabel")}
        </label>
        {typesError ? (
          <InlineQueryError error={typesError} onRetry={onRetryTypes} />
        ) : (
          <NativeSelect
            id="storage-type"
            value={storageTypeId ?? ""}
            onChange={(e) => onStorageTypeChange(e.target.value)}
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

      <div className="space-y-2">
        {ALL_TRACKING_FIELDS.map((key) => {
          const checked = effectiveFields.includes(key);
          const Icon = FIELD_ICONS[key];
          return (
            <Button
              key={key}
              variant={checked ? "secondary" : "outline"}
              onClick={() => toggleField(key)}
              className="w-full justify-start"
            >
              {Icon ? (
                <Icon
                  size={18}
                  className={`flex-shrink-0 ${checked ? "text-primary-600" : "text-on-muted"}`}
                />
              ) : (
                <span className="w-6 text-center text-on-muted">·</span>
              )}
              <span
                className={`flex-1 text-sm font-semibold ${checked ? "text-primary-800" : "text-on-secondary"}`}
              >
                {t(`locations:fieldLabels.${key}`, { defaultValue: key })}
              </span>
              {checked && (
                <Check size={16} className="text-primary-500 flex-shrink-0" />
              )}
            </Button>
          );
        })}
      </div>

      {/* Custom fields builder */}
      <div>
        <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted mb-2">
          {t("locations:onboarding.customFields")}
        </p>
        <FieldBuilder
          commitRef={fieldBuilderRef}
          fields={customFields}
          onChange={onCustomFieldsChange}
        />
      </div>

      <div>
        <Button
          size="content"
          variant="ghost"
          onClick={onToggleAdvanced}
          className="text-on-muted hover:text-on-secondary px-0 py-2 min-h-11 md:min-h-10"
        >
          <ChevronDown
            size={13}
            className={`transition-transform ${showAdvanced ? "rotate-180" : ""}`}
          />
          {t("locations:onboarding.advancedOptions")}
        </Button>
        {showAdvanced && (
          <div className="mt-3 space-y-3">
            <Textarea
              label={t("locations:onboarding.descriptionLabel")}
              rows={2}
              value={description}
              onChange={(e) => onDescriptionChange(e.target.value)}
              className="w-full bg-surface border border-border rounded-xl px-4 py-2.5 text-sm text-on focus:bg-surface-card focus:border-primary-400 outline-none transition-all resize-none"
              placeholder={t("locations:onboarding.descriptionPlaceholder")}
            />
            <div>
              <Input
                label={t("locations:onboarding.labelCodeLabel")}
                type="text"
                value={labelCode}
                onChange={(e) =>
                  onLabelCodeChange(e.target.value.toUpperCase())
                }
                leftIcon={<Barcode size={16} className="text-on-muted" />}
                className="font-mono"
                placeholder="LOC-001"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
