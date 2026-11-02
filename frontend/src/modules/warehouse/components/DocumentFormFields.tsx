import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Info } from "lucide-react";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { Textarea } from "@/components/ui/Textarea";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { LocationField } from "@/modules/warehouse/components/LocationField";
import type { LocationPickerEmptyReason } from "@/modules/shared/lib/locationPickerOffer";
import type { PartnerOption } from "@/hooks/usePartnerPicker";
import { ReasonCodeField } from "@/modules/shared/components/ReasonCodeField";
import {
  SCRAP_REASON_CODES,
  type ScrapReasonCode,
} from "@/modules/warehouse/reasonCodes";

/** Stable ids so a failed save can move focus to the first bad field. */
export const FIELD_IDS = {
  partner: "document-form-partner",
  source: "document-form-source-location",
  target: "document-form-target-location",
} as const;

interface DocumentFormFieldsProps {
  docType: string;
  partnerId: string;
  sourceLocationId: string;
  targetLocationId: string;
  scheduledDate: string;
  externalReference: string;
  notes: string;
  /** A scrap's reason, held by the workspace; ignored on every other type. */
  scrapReason?: {
    code: ScrapReasonCode | "";
    setCode: (value: ScrapReasonCode | "") => void;
  };
  requiresPartner: boolean;
  requiresSource: boolean;
  requiresTarget: boolean;
  partners: PartnerOption[];
  /** Hands the typed query to the server-side partner lookup. */
  onPartnerSearch?: (query: string) => void;
  partnersLoading?: boolean;
  /** Set only when the partner read failed. */
  partnersError?: unknown;
  retryPartners?: () => void;
  /** When true the Partners module is disabled — render a notice. */
  partnersModuleDisabled?: boolean;
  /**
   * Why the picker has nothing to offer, when it has nothing: the module
   * policy is hiding locations it would otherwise show, or there is nothing
   * to show at all. The two need different sentences — one is answered by a
   * setting, the other by creating a location — and `null` (an answer still
   * on its way) keeps the plain message.
   */
  locationsEmptyReason?: LocationPickerEmptyReason | null;
  errors: Record<string, string>;
  onPartnerIdChange: (value: string) => void;
  onSourceLocationIdChange: (value: string) => void;
  onTargetLocationIdChange: (value: string) => void;
  onScheduledDateChange: (value: string) => void;
  onExternalReferenceChange: (value: string) => void;
  onNotesChange: (value: string) => void;
  onPartnerCreate?: (query: string) => void;
}

export function DocumentFormFields({
  docType,
  partnerId,
  sourceLocationId,
  targetLocationId,
  scheduledDate,
  externalReference,
  notes,
  scrapReason,
  requiresPartner,
  requiresSource,
  requiresTarget,
  partners,
  onPartnerSearch,
  partnersLoading,
  partnersError,
  retryPartners,
  partnersModuleDisabled,
  locationsEmptyReason,
  errors,
  onPartnerIdChange,
  onSourceLocationIdChange,
  onTargetLocationIdChange,
  onScheduledDateChange,
  onExternalReferenceChange,
  onNotesChange,
  onPartnerCreate,
}: DocumentFormFieldsProps) {
  const { t } = useTranslation("warehouse");

  // What a location picker says when it has nothing to offer. The policy case
  // gets the way out — the switch that reveals the hidden locations, on the
  // deep link that lands on the switch itself rather than the top of a long
  // settings page.
  const locationsEmptyMessage =
    locationsEmptyReason === "module-data-hidden" ? (
      <>
        {t("form.noLocationsAllClaimed")}{" "}
        <Link
          to="/settings#module-data"
          className="font-semibold text-primary-600 hover:underline"
        >
          {t("form.openModuleDataSettings")}
        </Link>
      </>
    ) : locationsEmptyReason === "nothing-to-offer" ? (
      t("form.noOfferableLocations")
    ) : (
      t("form.noLocationsFound")
    );

  return (
    <>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {docType !== "INT" &&
          (partnersModuleDisabled ? (
            <div className="space-y-1.5">
              <p className="block text-xs font-medium uppercase text-on-secondary ml-1 tracking-wide">
                {t("fields.partner")}
              </p>
              <div className="flex items-start gap-2 rounded-lg border border-border bg-surface-inset p-3 text-xs text-on-secondary">
                <Info size={16} className="mt-0.5 shrink-0 text-on-muted" />
                <span>
                  {t("form.enablePartnersNotice")}{" "}
                  <Link
                    to="/apps?module=partners"
                    className="font-semibold text-primary-600 hover:underline"
                  >
                    {t("form.enablePartnersLink")}
                  </Link>
                </span>
              </div>
            </div>
          ) : (
            <SearchableCombobox
              id={FIELD_IDS.partner}
              label={t("fields.partner")}
              required={requiresPartner}
              error={errors.partner_id ? t(errors.partner_id) : undefined}
              options={partners}
              onSearchChange={onPartnerSearch}
              value={partnerId}
              onChange={onPartnerIdChange}
              placeholder={
                requiresPartner
                  ? t("form.selectPartnerRequired")
                  : t("form.selectPartner")
              }
              searchPlaceholder={t("form.searchPartner")}
              emptyMessage={
                // "No partners found" for a partner who exists but has the
                // wrong role reads as "this partner does not exist". Say
                // which role the field is narrowed to.
                docType === "OUT"
                  ? t("form.noCustomersFound")
                  : t("form.noSuppliersFound")
              }
              createLabel={t("form.createNewPartner")}
              title={t("fields.partner")}
              onCreateNew={onPartnerCreate}
              loading={partnersLoading}
            />
          ))}
        {partnersError != null && (
          <InlineQueryError
            error={partnersError}
            onRetry={retryPartners}
            className="sm:col-span-2"
          />
        )}

        {requiresSource && (
          <LocationField
            id={FIELD_IDS.source}
            label={t("fields.sourceLocation")}
            required
            error={
              errors.source_location_id
                ? t(errors.source_location_id)
                : undefined
            }
            value={sourceLocationId}
            onChange={onSourceLocationIdChange}
            placeholder={t("form.selectSource")}
            searchPlaceholder={t("form.searchLocation")}
            emptyMessage={locationsEmptyMessage}
            title={t("fields.sourceLocation")}
          />
        )}

        {requiresTarget && (
          <LocationField
            id={FIELD_IDS.target}
            except={requiresSource ? [sourceLocationId] : undefined}
            label={t("fields.targetLocation")}
            required
            error={
              errors.target_location_id
                ? t(errors.target_location_id)
                : undefined
            }
            value={targetLocationId}
            onChange={onTargetLocationIdChange}
            placeholder={t("form.selectTarget")}
            searchPlaceholder={t("form.searchLocation")}
            emptyMessage={locationsEmptyMessage}
            title={t("fields.targetLocation")}
          />
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 items-end gap-3">
        <DateInput
          label={t("fields.scheduledDate")}
          value={scheduledDate}
          onChange={(e) => onScheduledDateChange(e)}
        />
        <Input
          label={t("fields.externalReference")}
          value={externalReference}
          onChange={(e) => onExternalReferenceChange(e.target.value)}
        />
      </div>
      {docType === "SCRAP" && scrapReason ? (
        <ReasonCodeField
          testId="scrap-reason"
          label={t("reasons.scrap.label")}
          codes={SCRAP_REASON_CODES}
          labelFor={(c) => t(`reasons.scrap.codes.${c}`)}
          code={scrapReason.code}
          onCodeChange={scrapReason.setCode}
          note={notes}
          onNoteChange={onNotesChange}
          showErrors={errors.reason_code !== undefined}
        />
      ) : (
        <Textarea
          label={t("fields.notes")}
          className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-on placeholder:text-on-muted focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          rows={3}
          value={notes}
          onChange={(e) => onNotesChange(e.target.value)}
        />
      )}
    </>
  );
}
