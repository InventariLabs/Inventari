import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { CardLink } from "@/components/ui/CardLink";
import { cn } from "@/lib/utils";

/**
 * How urgent a row is, most urgent first. The order is the card's reading
 * order: something already past its date outranks something about to be,
 * which outranks a shortfall, which outranks a note.
 */
export type AttentionSeverity = "expired" | "expiring" | "low" | "info";

const SEVERITY_RANK: Record<AttentionSeverity, number> = {
  expired: 0,
  expiring: 1,
  low: 2,
  info: 3,
};

const SEVERITY_DOT: Record<AttentionSeverity, string> = {
  expired: "bg-red-500",
  expiring: "bg-amber-500",
  low: "bg-blue-600",
  info: "bg-gray-500",
};

// The row sits on the amber tint, so its coloured text uses the `text-on-*`
// half of each pair (UI_GUIDELINES §1.1) and needs no `dark:` override.
const SEVERITY_TEXT: Record<AttentionSeverity, string> = {
  expired: "text-on-danger",
  expiring: "text-on-warning",
  low: "text-on-info",
  info: "text-on-secondary",
};

export interface AttentionItem {
  id: string;
  severity: AttentionSeverity;
  /** The record's name — the row's link. */
  title: string;
  /** Why it is here: "expired yesterday", "low stock · 1 pc". */
  reason: string;
  /** Where it is. Wraps to a second line on a phone rather than vanishing. */
  where?: string;
  href: string;
}

/** Most urgent first; the caller's order holds within one severity. */
export function sortBySeverity(items: readonly AttentionItem[]) {
  return items
    .map((item, index) => ({ item, index }))
    .sort(
      (a, b) =>
        SEVERITY_RANK[a.item.severity] - SEVERITY_RANK[b.item.severity] ||
        a.index - b.index,
    )
    .map(({ item }) => item);
}

interface AttentionCardProps {
  items: readonly AttentionItem[];
  /** The busy heading, already counted: "3 items need attention". */
  attentionLabel: string;
  /** What the workspace holds, in both states: "84 products in 6 places". */
  summary?: string;
  linkLabel: string;
  linkHref: string;
  /** The one line shown when there is nothing to report. */
  quiet: { okText: string; linkLabel: string; linkHref: string };
  /**
   * The request behind the rows failed, or part of it did. The card then says
   * so instead of reading the missing answer as "nothing to report" — on the
   * one screen whose job is to answer exactly that.
   */
  unavailable?: {
    message: string;
    retryLabel: string;
    onRetry: () => void;
    /** Heading without a number: a count built from a failed source is not one. */
    partialLabel?: string;
  };
  /**
   * Some request behind the rows has not answered yet. The rows are empty
   * until it does, and an empty list is what the quiet line is drawn from —
   * so the card holds its tongue instead of announcing a quiet day.
   */
  loading?: boolean;
  /** An action on the whole set, placed beside the link. */
  actions?: ReactNode;
  /** Rows shown before the rest is left to the link. */
  maxItems?: number;
  /**
   * For a card whose link does not open the rows it counts: a button that
   * shows the rest here. Without it the rest is the link's to show.
   */
  showAllLabel?: string;
}

/**
 * The top of an overview: what needs doing, most urgent first — or, on a
 * quiet day, one green line saying nothing does.
 */
export function AttentionCard({
  items,
  attentionLabel,
  summary,
  linkLabel,
  linkHref,
  quiet,
  unavailable,
  loading = false,
  actions,
  maxItems = 5,
  showAllLabel,
}: AttentionCardProps) {
  const [showAll, setShowAll] = useState(false);
  const sorted = sortBySeverity(items);
  const rows = showAll ? sorted : sorted.slice(0, maxItems);
  const busy = rows.length > 0;

  if (loading && !busy && !unavailable) {
    return (
      <Card className="p-4 sm:px-5" aria-busy="true">
        <div className="flex items-center gap-3">
          <div className="h-5 w-5 shrink-0 animate-pulse rounded-full bg-surface-inset" />
          <div className="h-4 w-56 max-w-full animate-pulse rounded bg-surface-inset" />
        </div>
      </Card>
    );
  }

  if (!busy && !unavailable) {
    return (
      <Card className="p-4 sm:px-5">
        <StatusLine
          icon={
            <CheckCircle2
              size={18}
              className="shrink-0 text-on-success"
              aria-hidden="true"
            />
          }
          heading={quiet.okText}
          headingClassName="text-on"
          summary={summary}
          link={{ label: quiet.linkLabel, href: quiet.linkHref }}
          actions={actions}
        />
      </Card>
    );
  }

  return (
    <Card className={cn("p-4 sm:px-5", busy && "border-amber-100 bg-amber-50")}>
      {busy && (
        <StatusLine
          icon={
            <AlertTriangle
              size={18}
              className="shrink-0 text-on-warning"
              aria-hidden="true"
            />
          }
          heading={unavailable?.partialLabel ?? attentionLabel}
          headingClassName="text-on-warning"
          summary={summary}
          link={{ label: linkLabel, href: linkHref }}
          actions={actions}
        />
      )}
      {unavailable && (
        <div
          role="alert"
          className={cn(
            "flex items-center justify-between gap-3",
            busy && "mt-3",
          )}
        >
          <p className="text-sm text-on-warning">{unavailable.message}</p>
          <Button variant="outline" size="sm" onClick={unavailable.onRetry}>
            {unavailable.retryLabel}
          </Button>
        </div>
      )}
      {busy && (
        <ul className="mt-2 divide-y divide-amber-100">
          {rows.map((item) => (
            <AttentionRow key={item.id} item={item} />
          ))}
        </ul>
      )}
      {showAllLabel && rows.length < sorted.length && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1"
          onClick={() => setShowAll(true)}
        >
          {showAllLabel}
        </Button>
      )}
    </Card>
  );
}

function StatusLine({
  icon,
  heading,
  headingClassName,
  summary,
  link,
  actions,
}: {
  icon: ReactNode;
  heading: string;
  headingClassName: string;
  summary?: string;
  link: { label: string; href: string };
  actions?: ReactNode;
}) {
  // A card with an action beside the link wraps: the heading keeps at least
  // 12rem and the actions fall under it, where they used to leave it ~60px on
  // a phone, one word per line. A card with only the link keeps the single
  // row it always had -- the link beside a two-line heading, not under it.
  return (
    <div
      className={cn(
        "flex items-center",
        actions ? "flex-wrap gap-x-3 gap-y-2" : "gap-3",
      )}
    >
      <div
        className={cn(
          "flex min-w-0 flex-1 items-center gap-3",
          actions && "basis-48",
        )}
      >
        {icon}
        {/* Two lines at every width: side by side, "14 need attention 592
            records" read as one sentence about one number. */}
        <div className="min-w-0 flex-1">
          <h2 className={cn("text-sm font-semibold", headingClassName)}>
            {heading}
          </h2>
          {summary && (
            <p className="text-sm tabular-nums text-on-secondary">{summary}</p>
          )}
        </div>
      </div>
      {actions}
      <CardLink to={link.href} arrow className="text-xs">
        {link.label}
      </CardLink>
    </div>
  );
}

function AttentionRow({ item }: { item: AttentionItem }) {
  return (
    <li className="flex items-start gap-3 py-2.5">
      <span
        aria-hidden="true"
        className={cn(
          "mt-1.5 h-2 w-2 shrink-0 rounded-full",
          SEVERITY_DOT[item.severity],
        )}
      />
      {/* Below `sm` the reason and the place drop under the name; above it
          they share one line with the name in a fixed column. Nothing is
          hidden at either width. */}
      <div className="min-w-0 flex-1 sm:flex sm:items-baseline sm:gap-4">
        <Link
          to={item.href}
          className="block truncate text-sm font-semibold text-on hover:underline py-3 md:py-1 sm:w-56 sm:shrink-0"
        >
          {item.title}
        </Link>
        <p className="flex flex-wrap gap-x-3 text-xs">
          <span className={SEVERITY_TEXT[item.severity]}>{item.reason}</span>
          {item.where && (
            <span className="text-on-secondary">{item.where}</span>
          )}
        </p>
      </div>
    </li>
  );
}
