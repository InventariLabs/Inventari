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
  /**
   * `stack` (default): one full-width bar per action, for the narrow sheet over
   * the list. `inline`: for a page, where full-width bars would run the length
   * of the screen — content-wide buttons that wrap, the destructive action in
   * its own group at the far end. Below `sm` both are the same stack.
   */
  layout?: "stack" | "inline";
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

export function QuickActionGrid({
  actions,
  layout = "stack",
}: QuickActionGridProps) {
  if (layout === "stack") {
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

  const regular = actions.filter((action) => !action.danger);
  const destructive = actions.filter((action) => action.danger);
  const group = "flex flex-col gap-3 sm:flex-row sm:flex-wrap";
  const button = "w-full sm:w-auto justify-start py-3 px-4";
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-start sm:justify-between">
      <div className={group}>
        {regular.map((action) => (
          <ActionButton key={action.id} action={action} className={button} />
        ))}
      </div>
      {destructive.length > 0 && (
        <div className={group}>
          {destructive.map((action) => (
            <ActionButton key={action.id} action={action} className={button} />
          ))}
        </div>
      )}
    </div>
  );
}
