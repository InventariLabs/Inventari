import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

interface SelectionToolbarProps {
  /** How many rows are selected. Zero renders nothing. */
  count: number;
  /**
   * How many rows the list holds beyond this page, when the selection cannot
   * reach them. Given, the bar says the selection is of this page — "50
   * selected" over a filtered result of 150 is true of the page and false of
   * the list, and the difference only surfaced during a bulk edit.
   */
  totalBeyondPage?: number;
  onClear: () => void;
  /** The actions that apply to the selection, in a row after the count. */
  children: ReactNode;
  /**
   * A sentence about the selection's scope, on its own line under the count
   * and the actions — never squeezed beside them, where a phone left it one
   * word per line.
   */
  note?: ReactNode;
  /**
   * `wide` for a bar with three actions or more, whose last one would
   * otherwise start out of sight behind the scroll on every desktop.
   */
  width?: "default" | "wide";
  className?: string;
}

/**
 * The bar that appears once rows are selected: a floating pill with the count
 * on one side and the actions on the other.
 *
 * It floats rather than sitting in the page flow, and that is the whole point.
 * A selection is a temporary state, so its actions cannot take a permanent
 * band of the layout — the labels pool put two of them in the page header as
 * `flex-1` siblings, which on a desktop is two buttons each half the screen
 * wide, above a filter row and below a title that also has a button.
 *
 * `bottom-20` clears the mobile tab bar; `max-w-lg` keeps the pill readable on
 * a wide screen instead of stretching a toolbar across 1400px.
 */
export function SelectionToolbar({
  count,
  totalBeyondPage,
  onClear,
  children,
  width = "default",
  note,
  className,
}: SelectionToolbarProps) {
  const { t } = useTranslation("common");

  if (count === 0) return null;

  const scoped =
    totalBeyondPage !== undefined && totalBeyondPage > count
      ? t("selection.countOnPage", { count, total: totalBeyondPage })
      : t("selection.count", { count });

  return (
    <div className="fixed bottom-20 left-0 right-0 z-50 px-4">
      <div
        role="toolbar"
        aria-label={scoped}
        className={cn(
          "mx-auto rounded-2xl",
          width === "wide" ? "max-w-2xl" : "max-w-lg",
          "border border-border bg-surface-card p-3 shadow-lg",
          className,
        )}
      >
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <div className="flex shrink-0 items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              onClick={onClear}
              aria-label={t("actions.clearSelection")}
              title={t("actions.clearSelection")}
            >
              <X size={16} className="text-on-secondary" />
            </Button>
            <span className="text-sm font-semibold text-on tabular-nums">
              {scoped}
            </span>
          </div>

          {/* The actions wrap rather than scroll. A scrolled row hid its last
            action behind the screen edge on a phone — the labels pool's Print
            Preview sat out of sight beside a visible Delete — and nothing on
            the bar said more followed. Wrapping puts every action on screen:
            beside the count when they fit, on a line of their own when they
            do not. A contributed label is a phrase more often than a word, so
            a single action never breaks across lines. */}
          <div className="flex min-w-0 flex-wrap items-center gap-1 [&>*]:whitespace-nowrap">
            {children}
          </div>
        </div>
        {note && <div className="mt-2 text-xs text-on-secondary">{note}</div>}
      </div>
    </div>
  );
}
