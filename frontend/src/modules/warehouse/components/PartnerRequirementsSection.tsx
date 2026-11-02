import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/Checkbox";

interface PartnerRequirementsSectionProps {
  /** True/False is the profile's own entry; null defers to the country. */
  requireTaxId: boolean | null;
  onRequireTaxIdChange: (value: boolean) => void;
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
 */
export function PartnerRequirementsSection({
  requireTaxId,
  onRequireTaxIdChange,
  titleClassName,
  descriptionClassName,
}: PartnerRequirementsSectionProps) {
  const { t } = useTranslation("warehouse");
  return (
    <section className="space-y-6">
      <div>
        <h2 className={titleClassName}>{t("profile.partnerRequirements")}</h2>
        <p className={descriptionClassName}>
          {t("profile.partnerRequirementsHint")}
        </p>
      </div>
      <Checkbox
        checked={requireTaxId ?? false}
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
    </section>
  );
}
