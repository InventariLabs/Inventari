import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const cardVariants = cva("rounded-xl p-6 transition-all duration-200", {
  variants: {
    variant: {
      default: "bg-surface-card border border-border",
      elevated: "bg-surface-card shadow-md",
      ghost: "bg-surface border border-border",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

interface CardProps
  extends
    React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {
  /**
   * Lift the card under the pointer.
   *
   * It raises the shadow and nothing else. It used to add `cursor-pointer`
   * too, which is a promise the card cannot keep on its own: whether anything
   * happens on click is the caller's business, and one caller had it on a card
   * with no action at all. A pointing cursor belongs to the element that
   * actually does something — see the clickable-card pattern in
   * UI_GUIDELINES §2.3a, which puts a real link there instead.
   */
  hoverable?: boolean;
}

const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant, hoverable, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        cardVariants({ variant }),
        hoverable && "hover:shadow-lg",
        className,
      )}
      {...props}
    />
  ),
);
Card.displayName = "Card";

const CardHeader = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("flex flex-col space-y-1.5 pb-4", className)} {...props} />
);
CardHeader.displayName = "CardHeader";

interface CardTitleProps extends React.HTMLAttributes<HTMLHeadingElement> {
  /**
   * Heading level. The shell owns `h1` (the page title), so a card title is
   * the first level of content and defaults to `h2` — rendering `h3` here left
   * a hole in the outline that screen-reader users navigate by. Pass `h3` only
   * for a card nested inside a section that already has its own `h2`.
   */
  as?: "h2" | "h3" | "h4";
}

const CardTitle = ({ className, as: Tag = "h2", ...props }: CardTitleProps) => (
  <Tag
    className={cn(
      // Balance avoids single-word orphans in long PL/DE titles.
      "text-lg font-semibold text-on leading-tight tracking-tight text-balance",
      className,
    )}
    {...props}
  />
);
CardTitle.displayName = "CardTitle";

const CardDescription = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement>) => (
  <p
    className={cn(
      "text-sm text-on-secondary font-medium text-pretty",
      className,
    )}
    {...props}
  />
);
CardDescription.displayName = "CardDescription";

const CardContent = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("pt-0", className)} {...props} />
);
CardContent.displayName = "CardContent";

const CardFooter = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div
    className={cn(
      "flex items-center pt-4 border-t border-border mt-4",
      className,
    )}
    {...props}
  />
);
CardFooter.displayName = "CardFooter";

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardDescription,
  CardContent,
  cardVariants,
};
