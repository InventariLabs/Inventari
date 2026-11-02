import { ChevronDown, ChevronUp } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

interface CollapsibleDetailSectionProps {
  title: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  /** Padding around the body. Off for a body that brings its own. */
  padded?: boolean;
  className?: string;
}

/**
 * A titled section on the recipe detail that folds away.
 *
 * The page grew three of these — history, nutrition, cost — as separate copies,
 * and they had already drifted: one titled itself `text-on`, the others
 * `text-on-secondary`; one had a transition, the others did not; all three
 * hand-rolled `bg-surface-card rounded-2xl border` instead of `<Card>`, at the
 * 2xl radius that belongs to modals rather than the xl that belongs to cards.
 */
export function CollapsibleDetailSection({
  title,
  open,
  onToggle,
  children,
  padded = true,
  className,
}: CollapsibleDetailSectionProps) {
  return (
    <Card className={cn("p-0 shadow-sm overflow-hidden", className)}>
      <Button
        size="content"
        variant="ghost"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full justify-between px-5 py-3 text-sm font-semibold text-on-secondary rounded-none"
      >
        <span>{title}</span>
        {open ? (
          <ChevronUp size={16} aria-hidden="true" className="text-on-muted" />
        ) : (
          <ChevronDown size={16} aria-hidden="true" className="text-on-muted" />
        )}
      </Button>
      {open && <div className={cn(padded && "px-5 pb-4")}>{children}</div>}
    </Card>
  );
}
