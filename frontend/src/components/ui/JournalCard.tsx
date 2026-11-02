import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Card, CardHeader, CardTitle } from "@/components/ui/Card";
import { CardLink } from "@/components/ui/CardLink";
import { cn } from "@/lib/utils";

export type JournalTone = "success" | "info" | "warning" | "danger" | "neutral";

const TONE_DOT: Record<JournalTone, string> = {
  success: "bg-success-500",
  info: "bg-blue-600",
  warning: "bg-amber-500",
  danger: "bg-red-500",
  neutral: "bg-gray-500",
};

export interface JournalEntry {
  id: string;
  tone: JournalTone;
  /** The sentence; the record's name inside it goes in `<strong>`. */
  text: ReactNode;
  /** Already formatted — see `formatRecentMoment` in `utils/formatters`. */
  timeLabel: string;
  /** The machine-readable moment behind `timeLabel`, for `<time>`. */
  dateTime?: string;
  href?: string;
}

interface JournalCardProps {
  title: string;
  entries: readonly JournalEntry[];
  linkLabel: string;
  linkHref: string;
  /** What an empty journal says, and where things that fill it happen. */
  empty: { text: string; linkLabel?: string; linkHref?: string };
  /**
   * The rows have not arrived yet. Placeholders stand in for them; the empty
   * sentence would claim a fact nobody has measured.
   */
  loading?: boolean;
}

/**
 * The last few things that happened, newest first as given, each with the
 * moment it happened. Presentation only — the caller writes the sentences.
 */
export function JournalCard({
  title,
  entries,
  linkLabel,
  linkHref,
  empty,
  loading = false,
}: JournalCardProps) {
  return (
    <Card className="p-4 sm:p-5">
      <CardHeader className="flex-row items-baseline justify-between space-y-0 pb-2">
        <CardTitle>{title}</CardTitle>
        <CardLink to={linkHref} arrow className="text-xs">
          {linkLabel}
        </CardLink>
      </CardHeader>
      {loading ? (
        <ul aria-busy="true" className="divide-y divide-border">
          {[0, 1, 2].map((i) => (
            <li key={i} className="py-2.5">
              <span className="block h-4 w-2/3 animate-pulse rounded bg-surface-raised" />
            </li>
          ))}
        </ul>
      ) : entries.length > 0 ? (
        <ul className="divide-y divide-border">
          {entries.map((entry) => (
            <JournalRow key={entry.id} entry={entry} />
          ))}
        </ul>
      ) : (
        <p className="py-2.5 text-sm text-on-secondary">
          {empty.text}{" "}
          {empty.linkHref && empty.linkLabel && (
            <CardLink to={empty.linkHref}>{empty.linkLabel}</CardLink>
          )}
        </p>
      )}
    </Card>
  );
}

function JournalRow({ entry }: { entry: JournalEntry }) {
  const text = (
    <span className="text-sm text-on-secondary [&_strong]:font-semibold [&_strong]:text-on">
      {entry.text}
    </span>
  );
  return (
    <li className="flex items-baseline gap-3 py-2.5">
      <span
        aria-hidden="true"
        className={cn(
          "h-2 w-2 shrink-0 self-center rounded-full",
          TONE_DOT[entry.tone],
        )}
      />
      <div className="min-w-0 flex-1">
        {entry.href ? (
          <Link to={entry.href} className="hover:underline">
            {text}
          </Link>
        ) : (
          text
        )}
      </div>
      <time
        dateTime={entry.dateTime}
        className="shrink-0 text-right text-xs tabular-nums text-on-muted"
      >
        {entry.timeLabel}
      </time>
    </li>
  );
}
