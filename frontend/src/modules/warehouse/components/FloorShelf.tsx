import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { MapPin } from "lucide-react";
import { Button } from "@/components/ui/Button";
import ShelfConfirmation, {
  type ShelfConfirmationState,
} from "./ShelfConfirmation";

export interface FloorShelfPlace {
  /** The label's code; without one the name is the large line. */
  code: string | null;
  name: string;
}

interface Props {
  /** What the worker does there: "Put on", "Take from". */
  label: string;
  /** Null when nothing names a shelf: the block becomes the choice. */
  shelf: FloorShelfPlace | null;
  /** Why this shelf — the rule, the order, the record — in small type. */
  reason?: ReactNode;
  /** Set when the session asks for the shelf's label to be scanned. */
  confirmation?: ShelfConfirmationState | null;
  kind: "picking" | "receiving";
  /** The action that names a shelf. A flow with no choice to offer leaves it
   *  out, and the block stays hidden until a shelf exists. */
  onChoose?: () => void;
}

/**
 * The shelf of one floor step — receiving's item card, a put-away task, the
 * pick walk — read the same way on each: the code large, as it is printed on
 * the label the worker looks for, the name under it, why this shelf in small
 * type, and whether its label still has to be scanned. With no shelf to name
 * the block is the action that names one, never the warehouse itself.
 */
export default function FloorShelf({
  label,
  shelf,
  reason,
  confirmation,
  kind,
  onChoose,
}: Props) {
  const { t } = useTranslation("warehouse");
  if (!shelf) {
    if (!onChoose) return null;
    return (
      <Button
        variant="secondary"
        size="lg"
        className="w-full"
        leftIcon={<MapPin size={20} aria-hidden="true" />}
        onClick={onChoose}
      >
        {t("floorShelf.choose")}
      </Button>
    );
  }
  const code = shelf.code || shelf.name;
  return (
    <div className="flex items-start gap-3 rounded-lg bg-blue-50 p-3 text-on-info">
      <MapPin size={20} aria-hidden="true" className="mt-1 shrink-0" />
      <div className="min-w-0 space-y-0.5">
        <p className="text-sm">{label}</p>
        <p className="text-xl font-semibold tracking-tight break-words">
          {code}
        </p>
        {code !== shelf.name && <p className="text-base">{shelf.name}</p>}
        {reason && <div className="text-xs">{reason}</div>}
        {confirmation && <ShelfConfirmation state={confirmation} kind={kind} />}
      </div>
    </div>
  );
}
