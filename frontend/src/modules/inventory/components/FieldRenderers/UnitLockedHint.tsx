import { useTranslation } from "react-i18next";

/** Why the unit picker above is disabled: the record holds stock. */
export function UnitLockedHint() {
  const { t } = useTranslation(["items"]);
  return (
    <p className="text-xs text-on-muted ml-1">
      {t("items:form.unitLockedByStock")}
    </p>
  );
}
