import { Check } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

interface ExecutionActionsProps {
  isPending: boolean;
  onCancel: () => void;
  onSubmit: () => void;
  cancelText: string;
  submitText: string;
  /** Floats over the panel's foot on a phone; off while the camera is open,
   * whose picture and messages it would cover. */
  floating: boolean;
}

export function ExecutionActions({
  isPending,
  onCancel,
  onSubmit,
  cancelText,
  submitText,
  floating,
}: ExecutionActionsProps) {
  return (
    <div
      data-testid="document-execution-actions"
      className={cn(
        "-mx-1 flex flex-col-reverse gap-2 rounded-xl border border-border bg-surface-card/95 p-3 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-surface-card/85 sm:mx-0 sm:flex-row sm:justify-end sm:border-0 sm:bg-transparent sm:p-0 sm:shadow-none sm:backdrop-blur-0",
        floating && "sticky bottom-20 z-10 sm:static",
      )}
    >
      <Button variant="outline" onClick={onCancel} disabled={isPending}>
        {cancelText}
      </Button>
      <Button
        variant="primary"
        leftIcon={<Check size={16} />}
        onClick={onSubmit}
        isLoading={isPending}
      >
        {submitText}
      </Button>
    </div>
  );
}
