import { useTranslation } from "react-i18next";
import { LocationField } from "@/modules/warehouse/components/LocationField";

interface QuarantineLocationSectionProps {
  /** The location id the profile names, or "" for none. */
  quarantineLocationId: string;
  onQuarantineLocationIdChange: (value: string) => void;
  titleClassName: string;
  descriptionClassName: string;
}

/**
 * Where goods received under the codes Damage and Quality hold are put when
 * they carry no batch to hold back in place. A receipt that contains such a
 * line cannot be completed until one is named.
 */
export function QuarantineLocationSection({
  quarantineLocationId,
  onQuarantineLocationIdChange,
  titleClassName,
  descriptionClassName,
}: QuarantineLocationSectionProps) {
  const { t } = useTranslation("warehouse");
  return (
    <section className="space-y-6">
      <div>
        <h2 className={titleClassName}>{t("profile.quarantine")}</h2>
        <p className={descriptionClassName}>{t("profile.quarantineHint")}</p>
      </div>
      <LocationField
        id="profile-quarantine-location"
        scope={{ purpose: "general" }}
        label={t("profile.quarantineLocation")}
        value={quarantineLocationId}
        clearable
        clearLabel={t("profile.quarantineLocationNone")}
        onChange={onQuarantineLocationIdChange}
        placeholder={t("profile.quarantineLocationNone")}
        searchPlaceholder={t("form.searchLocation")}
        emptyMessage={t("form.noLocationsFound")}
        title={t("profile.quarantineLocation")}
      />
    </section>
  );
}
