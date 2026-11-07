import { useTranslation } from "react-i18next";
import {
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowUpFromLine,
  ClipboardCheck,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import { cn } from "@/lib/utils";

interface ActionTileProps {
  icon: LucideIcon;
  title: string;
  subtitle: string;
  /** The one action the screen leads with; the rest are equally available. */
  primary?: boolean;
  onClick: () => void;
}

/**
 * One way to start moving goods. A tile rather than a button: it carries the
 * plain sentence that says what the action is for, so a newcomer chooses
 * between four tasks instead of between document types.
 */
function ActionTile({
  icon: Icon,
  title,
  subtitle,
  primary = false,
  onClick,
}: ActionTileProps) {
  return (
    <Button
      variant={primary ? "primary" : "ghost"}
      size="row"
      onClick={onClick}
      className={cn(
        "flex-col items-start gap-1.5 rounded-xl border p-4 text-left whitespace-normal shadow-sm transition-shadow hover:shadow-md md:p-5",
        "min-h-24 md:min-h-32",
        primary
          ? "border-primary-700 bg-primary-700 text-white hover:bg-primary-800"
          : "border-border bg-surface-card text-on hover:bg-surface-card",
      )}
    >
      <Icon
        size={24}
        aria-hidden="true"
        className={primary ? "text-white" : "text-on-primary"}
      />
      <span className="text-base font-semibold tracking-tight">{title}</span>
      <span
        className={cn(
          "max-md:hidden text-sm",
          primary ? "text-white/85" : "text-on-secondary",
        )}
      >
        {subtitle}
      </span>
    </Button>
  );
}

/**
 * The four things a warehouse does in a day, in the order the day usually
 * runs. Each opens the one screen for that action; the document the office
 * needs is written in the background.
 */
export function StartActions({
  onReceive,
  onIssue,
  onMove,
  onCount,
}: {
  onReceive: () => void;
  onIssue: () => void;
  onMove: () => void;
  onCount: () => void;
}) {
  const { t } = useTranslation("warehouse");
  // The tiles start work that posts stock. A read-only account is told so by
  // the notice on the screen and is offered none of them. Counting is
  // `stock_takes` work, so its tile asks that key — the same one the
  // stock-takes screen and the API check — and the other three ask the
  // warehouse's own.
  const canMove = useCanWrite("warehouse");
  const canCount = useCanWrite("stock_takes");
  if (!canMove && !canCount) return null;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
      {canMove && (
        <>
          <ActionTile
            icon={ArrowDownToLine}
            title={t("start.actions.receive.title")}
            subtitle={t("start.actions.receive.subtitle")}
            primary
            onClick={onReceive}
          />
          <ActionTile
            icon={ArrowUpFromLine}
            title={t("start.actions.issue.title")}
            subtitle={t("start.actions.issue.subtitle")}
            onClick={onIssue}
          />
          <ActionTile
            icon={ArrowLeftRight}
            title={t("start.actions.move.title")}
            subtitle={t("start.actions.move.subtitle")}
            onClick={onMove}
          />
        </>
      )}
      {canCount && (
        <ActionTile
          icon={ClipboardCheck}
          title={t("start.actions.count.title")}
          subtitle={t("start.actions.count.subtitle")}
          onClick={onCount}
        />
      )}
    </div>
  );
}
