import { Scale } from "lucide-react";
import { EmptyState } from "@/components/ui/EmptyState";

interface UnitConversionsEmptyStateProps {
  t: (key: string) => string;
}

export function UnitConversionsEmptyState({
  t,
}: UnitConversionsEmptyStateProps) {
  return (
    <EmptyState
      variant="compact"
      icon={Scale}
      title={t("recipes:unit_conversions.empty")}
      description={t("recipes:unit_conversions.empty_description")}
    />
  );
}
