import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center font-medium transition-all duration-200 active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
  {
    variants: {
      variant: {
        // Filled variants carry white labels at 12-14px, so their background
        // has to clear 4.5:1 against white. The ramp step below each one does
        // not: primary-600 is 3.74:1, red-500 3.76:1, success-500 2.54:1.
        // Only the primary fill needs a dark-theme step of its own: a product
        // profile's palette takes its 700 step to the ramp's 400 under `.dark`
        // (useProfileTheme) so that *text* in primary-700 stays readable on a
        // dark card, and a fill on that step turns into the light shade — white
        // on it measured 1.92:1. 800 passes through unchanged in both palettes.
        default:
          "bg-primary-700 text-white hover:bg-primary-800 active:bg-primary-900 shadow-sm dark:bg-primary-800 dark:hover:bg-primary-900",
        primary:
          "bg-primary-700 text-white hover:bg-primary-800 active:bg-primary-900 shadow-sm dark:bg-primary-800 dark:hover:bg-primary-900",
        secondary:
          "bg-surface-raised text-on hover:bg-surface-inset active:bg-surface-inset",
        outline:
          "border border-border bg-surface-card hover:bg-surface-raised active:bg-surface-raised text-on-secondary",
        ghost:
          "bg-transparent hover:bg-surface-raised active:bg-surface-raised text-on-secondary",
        destructive:
          "bg-red-600 text-white hover:bg-red-700 active:bg-red-800 shadow-sm",
        danger:
          "bg-red-600 text-white hover:bg-red-700 active:bg-red-800 shadow-sm",
        // A destructive action inside a list row, where a filled red button
        // would outweigh the row itself. Carries the warning in the label
        // colour rather than only on hover — a "Deactivate" that looks exactly
        // like "Edit" until the pointer is on it is a trap on a touch screen.
        ghostDanger:
          "bg-transparent text-on-danger hover:bg-red-100 active:bg-red-100",
        // Jumps 500 -> 800 rather than -> 700: `--color-success-700` is remapped
        // in `.dark` to the bright shade so that *text* clears AA on a dark
        // card, which makes that step unusable as a filled background. Hover
        // and active share 900 because the ramp ends there; the press feedback
        // is the `active:scale` in the base class.
        success:
          "bg-success-800 text-white hover:bg-success-900 active:bg-success-900 shadow-sm",
        link: "text-on-primary underline-offset-4 hover:underline",
      },
      size: {
        // 44px touch targets below `md:`; desktop keeps its density. Font size
        // and padding still separate the sizes — only the touch height is
        // shared, because a thumb is the same size whichever button it lands on.
        default: "h-11 px-4 text-sm gap-2 rounded-lg md:h-10",
        sm: "h-11 px-3 text-xs gap-1.5 rounded-lg md:h-8",
        md: "h-11 px-4 text-sm gap-2 rounded-lg md:h-10",
        lg: "h-12 px-6 text-base gap-2.5 rounded-xl",
        // `gap-2` like every other size. An icon-only button has nothing to
        // space, so it costs nothing there — but the moment a call site widens
        // the button to show its label beside the icon (`md:w-auto md:px-3`),
        // the glyph and the word were touching, and that is what the row of
        // partner actions shipped as.
        icon: "h-11 w-11 p-2 gap-2 rounded-lg md:h-10 md:w-10",
        // Deliberately free of responsive modifiers. `cn()` is `twMerge`, and
        // twMerge does not drop `md:h-10` for a plain `h-8` — an override in
        // `className` wins below `md` and loses on every desktop, silently.
        // So sizes smaller than the touch target are variants, not overrides.
        // `iconSm` — compact control inside a row or an action bar.
        iconSm: "h-8 w-8 p-1.5 gap-1.5 rounded-lg",
        // `inline` — an element that reads as an icon inside content (a colour
        // swatch, a star on a tile). Below the 44px touch floor on purpose, so
        // only where it sits next to a larger target or the whole surface is
        // clickable.
        inline: "h-auto w-auto p-0 rounded-md",
        // `row` — a full-width row whose height comes from what it holds: a
        // thumbnail or an icon beside two lines of text. The same reasoning
        // as above, from the other end: `h-auto` in a className loses to a
        // size's `md:h-10`, so above `md` the row was clipped to 40px and its
        // own content overlapped — which reads as missing margins, not as a
        // height that was overruled.
        row: "h-auto w-full justify-start text-left text-sm gap-3 px-3 py-3 rounded-lg",
        // `content` / `contentSm` — `default` and `sm` with the height left
        // to the content. Everything else about them is identical, so a call
        // site that used to write `h-auto` in its className moves across
        // without changing a pixel below `md` — and stops being clipped above
        // it. They exist because the height is the only part of a size that
        // cannot be overridden from outside.
        content: "h-auto px-4 text-sm gap-2 rounded-lg",
        contentSm: "h-auto px-3 text-xs gap-1.5 rounded-lg",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends
    React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  isLoading?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "default",
      size = "default",
      isLoading,
      leftIcon,
      rightIcon,
      children,
      disabled,
      ...props
    },
    ref,
  ) => {
    return (
      <button
        ref={ref}
        disabled={disabled || isLoading}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      >
        {/* The spinner replaces the leading icon, never the label: a button
            that becomes a bare dot stops saying what is taking time — and on
            a slow SMTP test that dot spanned two minutes. */}
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-current" />
        ) : (
          leftIcon
        )}
        {children}
        {!isLoading && rightIcon}
      </button>
    );
  },
);

Button.displayName = "Button";

export { Button, buttonVariants };
export default Button;
