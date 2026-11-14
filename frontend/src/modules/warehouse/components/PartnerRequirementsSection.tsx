import { useId } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { useCountryTaxRates } from "@/modules/warehouse/hooks/useTaxRates";

interface PartnerRequirementsSectionProps {
  /** True/False is the profile's own entry; null defers to the country. */
  requireTaxId: boolean | null;
  onRequireTaxIdChange: (value: boolean | null) => void;
  titleClassName: string;
  descriptionClassName: string;
}

/**
 * The one rule a document profile enforces about the partner it names.
 *
 * The switch is narrower than its label: confirmation checks the tax ID of the
 * partner named on the document, so a document with no partner passes either
 * way, and the ID itself is stored exactly as typed. Saying both here is
 * cheaper than the reader finding out from a document that confirmed when they
 * expected a refusal.
 *
 * With no entry of its own the profile follows the country, and confirmation
 * answers with the country's rule — so the checkbox shows that rule and says
 * where it came from, instead of an unchecked box over a refusal.
 */
export function PartnerRequirementsSection({
  requireTaxId,
  onRequireTaxIdChange,
  titleClassName,
  descriptionClassName,
}: PartnerRequirementsSectionProps) {
  const { t } = useTranslation("warehouse");
  const { data: offer } = useCountryTaxRates();
  const sourceId = useId();
  const offerKnown = offer !== undefined;
  const country = offer?.country ?? null;
  const inherited = requireTaxId === null;
  const countryRequires = offer?.require_partner_tax_id ?? false;
  return (
    <section className="space-y-6">
      <div>
        <h2 className={titleClassName}>{t("profile.partnerRequirements")}</h2>
        <p className={descriptionClassName}>
          {t("profile.partnerRequirementsHint")}
        </p>
      </div>
      <Checkbox
        checked={requireTaxId ?? countryRequires}
        aria-describedby={sourceId}
        onChange={(e) => onRequireTaxIdChange(e.target.checked)}
        className="h-4 w-4 cursor-pointer"
        label={
          <span className="text-sm font-medium text-on">
            {t("profile.requirePartnerTaxId")}
            <span className="block text-xs font-normal text-on-muted">
              {t("profile.requirePartnerTaxIdHint")}
            </span>
          </span>
        }
      />
      {inherited ? (
        <p
          id={sourceId}
          className="-mt-3 text-xs text-on-muted"
          data-testid="tax-id-source"
        >
          {!offerKnown
            ? t("profile.requirePartnerTaxIdFromUnknownCountry")
            : !country
              ? t("profile.requirePartnerTaxIdFromNoCountry")
              : countryRequires
                ? t("profile.requirePartnerTaxIdFromCountryYes", { country })
                : t("profile.requirePartnerTaxIdFromCountryNo", { country })}
        </p>
      ) : (
        <div className="-mt-3 flex flex-wrap items-center gap-3">
          <p
            id={sourceId}
            className="text-xs text-on-muted"
            data-testid="tax-id-source"
          >
            {t("profile.requirePartnerTaxIdOwn")}
          </p>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => onRequireTaxIdChange(null)}
          >
            {t("profile.requirePartnerTaxIdFollowCountry")}
          </Button>
        </div>
      )}
    </section>
  );
}
