import React from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";

interface QuickAction {
  id: string;
  label: string;
  icon: React.ElementType;
  color: string;
  accentBorder: string;
  onClick: () => void;
  isLoading?: boolean;
  disabled?: boolean;
  danger?: boolean;
}

interface QuickActionGridProps {
  actions: QuickAction[];
}

function ActionButton({
  action,
  className,
}: {
  action: QuickAction;
  className: string;
}) {
  return (
    <Button
      size="content"
      variant="outline"
      onClick={action.onClick}
      disabled={action.isLoading || action.disabled}
      className={`min-h-11 ${className} ${action.accentBorder} border-l-4`}
    >
      <div
        className={`p-2 rounded-lg bg-surface-card shadow-sm ${action.color}`}
      >
        <action.icon size={20} />
      </div>
      <span
        className={`font-semibold text-sm ${action.danger ? action.color : "text-on"}`}
      >
        {action.label}
      </span>
      {action.isLoading && (
        <RefreshCw size={18} className="animate-spin ml-auto opacity-50" />
      )}
    </Button>
  );
}

/**
 * One full-width bar per action, for the narrow sheet over the list. A page
 * shows the same actions as ordinary buttons in its header (ItemDetailActions).
 */
export function QuickActionGrid({ actions }: QuickActionGridProps) {
  return (
    <div className="grid grid-cols-1 gap-3">
      {actions.map((action) => (
        <ActionButton
          key={action.id}
          action={action}
          className="w-full justify-start py-4 px-4"
        />
      ))}
    </div>
  );
}
