import type { ReactNode } from "react";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

/** An active list filter above the results, with the cross that clears it. */
export function ClearableFilterBadge({
  label,
  clearLabel,
  onClear,
}: {
  label: ReactNode;
  clearLabel: string;
  onClear: () => void;
}) {
  return (
    <Badge variant="outline" className="gap-1">
      {label}
      <Button
        type="button"
        variant="ghost"
        size="inline"
        aria-label={clearLabel}
        onClick={onClear}
        className="p-0.5 text-on-muted hover:text-red-600 hover:bg-transparent"
      >
        <X size={12} />
      </Button>
    </Badge>
  );
}
