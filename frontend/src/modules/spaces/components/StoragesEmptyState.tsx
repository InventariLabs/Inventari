import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { EyeOff, MapPin, Plus, Settings } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

interface StoragesEmptyStateProps {
  /** Whether the module-data policy is keeping locations off this list. */
  hasHidden: boolean;
  /** Opens the wizard on the "add the first location" path. */
  onAddFirst: () => void;
}

/**
 * What the locations list says when it has no rows to show.
 *
 * Two different facts wear the same zero, and the screen may not render
 * them as one: an organization that has no locations yet, and one whose
 * locations all belong to a module the policy keeps off general lists.
 * Answering the second with "no storages defined" read as the app losing
 * data, and its create button read as an invitation to make duplicates.
 */
export function StoragesEmptyState({
  hasHidden,
  onAddFirst,
}: StoragesEmptyStateProps) {
  const { t } = useTranslation(["locations"]);
  const navigate = useNavigate();

  if (hasHidden) {
    return (
      <EmptyState
        icon={EyeOff}
        title={t("locations:hidden.title")}
        description={t("locations:hidden.description")}
        primaryAction={
          <Button
            onClick={() => navigate("/settings#module-data")}
            leftIcon={<Settings size={16} />}
          >
            {t("locations:hidden.openSettings")}
          </Button>
        }
      />
    );
  }

  return (
    <div className="py-20 flex flex-col items-center justify-center text-center max-w-sm mx-auto">
      <div className="w-20 h-20 rounded-2xl bg-primary-50 flex items-center justify-center mb-6">
        <MapPin size={36} className="text-primary-400" />
      </div>
      <h3 className="text-xl font-semibold text-on mb-2">
        {t("locations:empty.title")}
      </h3>
      <p className="text-on-secondary text-sm mb-8">
        {t("locations:empty.subtitle")}
      </p>
      <Button
        onClick={onAddFirst}
        className="w-full"
        leftIcon={<Plus size={16} />}
      >
        {t("locations:empty.addFirst")}
      </Button>
    </div>
  );
}
