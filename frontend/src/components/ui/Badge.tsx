import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  // Sentence case, medium weight. Uppercase says "this is a label, not
  // content" — a signal that stops working when fifty things on a screen are
  // labels: `maker` rendered 51 uppercase runs, `inventory` 6. It is reserved
  // for the two places it still carries meaning, a column header and a status
  // pill, and `StatusBadge` adds it back for the second of those.
  "inline-flex items-center rounded-lg px-2 py-0.5 text-[10px] font-medium transition-colors",
  {
    variants: {
      variant: {
        // A white label at 10px needs 4.5:1: primary-600 gives 3.77. The fill
        // takes the same pair as the primary Button, 700 in light and 800 under
        // `.dark`, where a profile palette moves 700 to its light shade.
        default:
          "bg-primary-700 text-white shadow-sm shadow-primary-100 dark:bg-primary-800",
        secondary: "bg-surface-raised text-on",
        outline: "text-on-secondary border border-border",
        // The status variants carry no `dark:` override on purpose: both halves
        // of the pair are theme-aware tokens. The tint (`bg-*-100`) flips to a
        // dark shade and `text-on-*` flips to a light one, so the badge keeps
        // its status colour in dark mode instead of collapsing to a grey chip
        // with unreadable text (APPROVED measured 1.9:1 before).
        //
        // No border either. A list of fifty rows carried a hundred outlines —
        // one per card and one per badge — and nothing stood out because
        // everything was framed. The deeper tint separates the badge from the
        // card it sits on, which is what the outline was doing.
        danger: "bg-red-100 text-on-danger",
        success: "bg-success-100 text-on-success",
        warning: "bg-amber-100 text-on-warning",
        info: "bg-blue-100 text-on-info",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends
    React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  // A span, not a div: the badge looks inline and is used inside
  // paragraphs, list text and table cells. A div there is invalid HTML —
  // the parser closes the paragraph before it, React logs
  // validateDOMNesting, and hydration meets a different tree than the
  // server rendered. `inline-flex` keeps the appearance.
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
