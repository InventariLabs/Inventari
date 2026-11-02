import { useTranslation } from "react-i18next";
import { CheckCircle2, ScanLine } from "lucide-react";
import { cn } from "@/lib/utils";

export type ShelfConfirmationState = "confirmed" | "toScan";

interface ShelfSession {
  shelf_scan_required?: boolean;
  confirmed_shelf_id?: string | null;
}

/**
 * Where a line stands against the shelf label, or null when the session does
 * not ask for one (the setting is off, or the line names no shelf).
 */
export function shelfConfirmationState(
  session: ShelfSession | null | undefined,
  expectedShelfId: string | null | undefined,
): ShelfConfirmationState | null {
  if (!session?.shelf_scan_required || !expectedShelfId) return null;
  return session.confirmed_shelf_id === expectedShelfId
    ? "confirmed"
    : "toScan";
}

interface DestinationSession {
  destination_shelf_id?: string | null;
}

/**
 * Whether every line is answered and the transfer's destination label is
 * still to be scanned — the picking sheet then asks for it, instead of
 * showing the summary. Nothing picked means nothing to confirm; the server
 * applies the same rule.
 */
export function awaitsDestination(
  session: DestinationSession | null | undefined,
  lines: { status: string; picked_quantity: number }[],
): boolean {
  return (
    Boolean(session?.destination_shelf_id) &&
    lines.every((ln) => ln.status !== "pending") &&
    lines.some((ln) => ln.picked_quantity > 0)
  );
}

interface Props {
  state: ShelfConfirmationState;
  kind: "picking" | "receiving";
}

/** The line's shelf label state: done, or still to be scanned before the product. */
export default function ShelfConfirmation({ state, kind }: Props) {
  const { t } = useTranslation("warehouse");
  const labels = {
    picking: {
      confirmed: t("picking.shelf.confirmed"),
      toScan: t("picking.shelf.toScan"),
    },
    receiving: {
      confirmed: t("receiving.shelf.confirmed"),
      toScan: t("receiving.shelf.toScan"),
    },
  };
  const confirmed = state === "confirmed";
  const Icon = confirmed ? CheckCircle2 : ScanLine;
  return (
    <p
      className={cn(
        "flex items-center gap-1 text-xs font-medium",
        confirmed ? "text-success-700" : "text-amber-700",
      )}
    >
      <Icon size={12} className="shrink-0" />
      {labels[kind][state]}
    </p>
  );
}
