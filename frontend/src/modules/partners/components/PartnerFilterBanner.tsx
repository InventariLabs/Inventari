import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { usePartner } from "@/modules/partners/hooks/usePartners";

interface PartnerFilterBannerProps {
  /** From `?partner_id=` — null when the list is not filtered. */
  partnerId: string | null;
  /**
   * The sentence naming the filter, built by the caller: each list phrases it
   * in its own words ("Documents for X" / "Orders for X"), and taking the
   * finished string keeps their `t()` calls literal for the i18n checker.
   */
  label: (partnerName: string) => string;
  onClear: () => void;
}

/**
 * Names the partner a list is filtered to, with a way back to all of it.
 *
 * The partner card links into the document and order lists filtered to one
 * supplier. Arriving at a shorter list with nothing to explain it
 * reads as data loss, so the list says whose records these are — and the id
 * stands in until the partner's name arrives, or if it never does.
 */
export function PartnerFilterBanner({
  partnerId,
  label,
  onClear,
}: PartnerFilterBannerProps) {
  const { t } = useTranslation("common");
  const { data: partner } = usePartner(partnerId);

  if (!partnerId) return null;

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-on-secondary">
        {label(partner?.name ?? partnerId)}
      </span>
      <Button size="sm" variant="ghost" onClick={onClear}>
        {t("actions.showAll")}
      </Button>
    </div>
  );
}
