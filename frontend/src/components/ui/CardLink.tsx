import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface CardLinkProps {
  to: string;
  children: ReactNode;
  /** The trailing arrow, for a link that leads out of the card. */
  arrow?: boolean;
  className?: string;
}

/**
 * A small text link in a card — "View all →" in a header, "Go to products"
 * in an empty state.
 *
 * The colour is the brand-text token the wordmark takes (`text-on-primary`;
 * `statusTokenContrast.test.ts` measures it): `primary-600`, the colour these
 * links used to take, reads 3.6:1 on the amber attention card and under 4:1
 * in dark mode, and the raw dark step is the profile's own 500 — 4.05:1 under
 * the blue palette. The token is short of neither.
 */
export function CardLink({
  to,
  children,
  arrow = false,
  className,
}: CardLinkProps) {
  return (
    <Link
      to={to}
      className={cn(
        // min-h-11 below `md`: a 16px-high text link is a miss on a phone.
        "inline-flex min-h-11 shrink-0 items-center gap-1 font-medium text-on-primary hover:underline md:min-h-0",
        className,
      )}
    >
      {children}
      {arrow && <ArrowRight size={14} aria-hidden="true" />}
    </Link>
  );
}
