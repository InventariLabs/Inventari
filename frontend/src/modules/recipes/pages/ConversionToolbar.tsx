import { Plus } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ListControlBar } from "@/components/ui/ListControlBar";

interface ConversionToolbarProps {
  q: string;
  onSearch: (value: string) => void;
  onToggleAdd: () => void;
  /** Whether to offer the add form — creating a conversion is a write. */
  canWrite?: boolean;
  t: (key: string) => string;
}

export function ConversionToolbar({
  q,
  onSearch,
  onToggleAdd,
  canWrite = true,
  t,
}: ConversionToolbarProps) {
  return (
    <ListControlBar
      search={{
        value: q,
        onChange: onSearch,
        placeholder: t("recipes:unit_conversions.search_placeholder"),
      }}
      primaryAction={
        canWrite ? (
          <Button size="sm" onClick={onToggleAdd}>
            <Plus size={16} className="mr-1" />
            {t("recipes:unit_conversions.add")}
          </Button>
        ) : undefined
      }
    />
  );
}
