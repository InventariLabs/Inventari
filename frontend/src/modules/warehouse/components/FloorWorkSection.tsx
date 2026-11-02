import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/Checkbox";

interface FloorWorkSectionProps {
  confirmShelfByScan: boolean;
  onConfirmShelfByScanChange: (value: boolean) => void;
  titleClassName: string;
  descriptionClassName: string;
}

/**
 * How the scan sessions on the floor are worked: today, whether they ask for
 * the shelf's label before the product standing on it.
 */
export function FloorWorkSection({
  confirmShelfByScan,
  onConfirmShelfByScanChange,
  titleClassName,
  descriptionClassName,
}: FloorWorkSectionProps) {
  const { t } = useTranslation("warehouse");
  return (
    <section className="space-y-6">
      <div>
        <h2 className={titleClassName}>{t("profile.floorWork")}</h2>
        <p className={descriptionClassName}>{t("profile.floorWorkHint")}</p>
      </div>
      <Checkbox
        checked={confirmShelfByScan}
        onChange={(e) => onConfirmShelfByScanChange(e.target.checked)}
        className="h-4 w-4 cursor-pointer"
        label={
          <span className="text-sm font-medium text-on">
            {t("profile.confirmShelfByScan")}
            <span className="block text-xs font-normal text-on-muted">
              {t("profile.confirmShelfByScanHint")}
            </span>
          </span>
        }
      />
    </section>
  );
}
