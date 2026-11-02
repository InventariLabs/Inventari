import { useTranslation } from "react-i18next";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { ProfilePresetSelector } from "@/modules/warehouse/components/ProfilePresetSelector";

interface ProfilePresetsSectionProps {
  selectedPreset: string;
  presets: string[];
  isPending: boolean;
  onChange: (preset: string) => void;
  onApply: (preset: string) => void;
  /** The preset list failed to load: say so instead of offering an empty one. */
  error: unknown;
  failed: boolean;
  onRetry: () => void;
  titleClassName: string;
  descriptionClassName: string;
}

/** The preset picker with its heading, and the way out when its list failed. */
export function ProfilePresetsSection({
  selectedPreset,
  presets,
  isPending,
  onChange,
  onApply,
  error,
  failed,
  onRetry,
  titleClassName,
  descriptionClassName,
}: ProfilePresetsSectionProps) {
  const { t } = useTranslation("warehouse");
  return (
    <section className="space-y-6">
      <div>
        <h2 className={titleClassName}>{t("profile.presetsLabel")}</h2>
        <p className={descriptionClassName}>{t("profile.presetsHint")}</p>
      </div>
      <ProfilePresetSelector
        selectedPreset={selectedPreset}
        presets={presets}
        isPending={isPending}
        onChange={onChange}
        onApply={onApply}
      />
      {failed && <InlineQueryError error={error} onRetry={onRetry} />}
    </section>
  );
}
