import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

interface TabsProps {
  defaultValue: string;
  value?: string;
  onValueChange?: (value: string) => void;
  children: React.ReactNode;
  className?: string;
  /** Which arrow keys move between tabs; set it when the list is laid out as a column. */
  orientation?: "horizontal" | "vertical";
  /**
   * Whether this root mounts a `TabsContent` for its tabs. A bar that filters
   * a list or switches a view rendered outside the root has no panel to
   * name, and Radix stamps `aria-controls` on every trigger regardless — so
   * the selected tab pointed at an id nothing on the page carries. Pass
   * `false` and the triggers name no panel.
   */
  panels?: boolean;
}

/** Whether the triggers under this root have panels to point at. */
const TabsPanelsContext = React.createContext(true);

const Tabs = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Root>,
  TabsProps
>(
  (
    {
      defaultValue,
      value,
      onValueChange,
      children,
      className,
      orientation,
      panels = true,
    },
    ref,
  ) => {
    const [internalValue, setInternalValue] = React.useState(defaultValue);
    const activeTab = value ?? internalValue;

    const handleValueChange = (newValue: string) => {
      setInternalValue(newValue);
      onValueChange?.(newValue);
    };

    return (
      <TabsPrimitive.Root
        ref={ref}
        value={activeTab}
        onValueChange={handleValueChange}
        defaultValue={defaultValue}
        orientation={orientation}
        className={className}
      >
        <TabsPanelsContext.Provider value={panels}>
          {children}
        </TabsPanelsContext.Provider>
      </TabsPrimitive.Root>
    );
  },
);
Tabs.displayName = "Tabs";

interface TabsListProps extends React.ComponentPropsWithoutRef<
  typeof TabsPrimitive.List
> {
  /**
   * The bar scrolls its own tabs sideways rather than pushing them off the
   * screen. On by default — see the comment on the class below.
   */
  scrollable?: boolean;
}

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  TabsListProps
>(({ className, scrollable = true, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      // The bar is as tall as the tabs it holds, plus its own padding, at
      // every width. It used to be pinned to 40px above `md:`, which leaves
      // 28px between the paddings — the height of a `size="sm"` tab exactly,
      // and 12px short of a default one. The oversized tab filled the padding
      // it was supposed to sit inside, and the ring that marks it active is
      // drawn just outside its box, so the top and bottom of that ring fell
      // outside the scrollport and were clipped away. Sides survived, because
      // sideways there was room.
      //
      // Nothing about a `size="sm"` bar moves: 28px of tab plus 12px of
      // padding is the 40px it always was.
      "inline-flex h-auto items-center rounded-xl bg-surface-raised/50 p-1.5 text-on-secondary",
      // `safe center` is `center` until the row overflows and `start` after —
      // a plain `justify-center` in a scroll container puts the first tab at
      // negative scroll offset, where no gesture can reach it.
      "[justify-content:safe_center]",
      // The bar is `inline-flex` with `whitespace-nowrap` tabs, so past four
      // or five of them it simply runs off a phone and takes the page with it
      // sideways. Ten call sites answered that four different ways or not at
      // all, so the bar answers it: it stops at the width it is given and
      // scrolls inside.
      //
      // No `ScrollRow` here, deliberately. Its fade is a mask on the element,
      // and this element carries the rounded pill background — the mask would
      // eat the pill's own corners. The pill's edge is the boundary a
      // `ScrollRow` on a bare row has to draw for itself.
      scrollable &&
        "max-w-full overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
      className,
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

interface TabsTriggerProps extends React.ComponentPropsWithoutRef<
  typeof TabsPrimitive.Trigger
> {
  icon?: React.ReactNode;
  size?: "sm" | "default";
}

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  TabsTriggerProps
>(({ className, icon, children, size, ...props }, ref) => {
  const hasPanels = React.useContext(TabsPanelsContext);
  return (
    <TabsPrimitive.Trigger
      ref={ref}
      // Radix spreads these props after its own, so `undefined` here removes
      // the reference it would make to a panel that is never mounted.
      {...(!hasPanels && { "aria-controls": undefined })}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg font-medium ring-offset-background transition-all duration-200 overflow-hidden",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
        "disabled:pointer-events-none disabled:opacity-50",
        // The raised card background and the ring carry "active"; the label stays
        // on the neutral text token. `primary-600` was a brand colour on a
        // surface — 4.0:1 in dark mode, and whatever a product profile repaints
        // the ramp with after that.
        "data-[state=active]:bg-surface-card data-[state=active]:text-on data-[state=active]:font-semibold data-[state=active]:shadow-sm",
        "data-[state=inactive]:text-on-secondary data-[state=inactive]:hover:text-on data-[state=inactive]:hover:bg-surface-card/50",
        // 44px touch target on a phone, both axes — a short label like "All"
        // clears the height but not the width. The compact tab returns above `md:`.
        "h-11 min-w-11 md:h-auto md:min-w-0",
        size === "sm"
          ? "px-3 md:py-1.5 text-xs gap-1 rounded-lg data-[state=active]:ring-1 data-[state=active]:ring-border/60"
          : "px-3 sm:px-6 md:py-2.5 text-xs sm:text-sm data-[state=active]:ring-1 data-[state=active]:ring-gray-200 dark:data-[state=active]:ring-border",
        "flex-none",
        className,
      )}
      {...props}
    >
      {icon}
      {children}
    </TabsPrimitive.Trigger>
  );
});
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

interface TabsContentProps extends React.ComponentPropsWithoutRef<
  typeof TabsPrimitive.Content
> {
  /**
   * Lay the panel over its siblings in one grid cell instead of swapping it
   * for them. Every panel stays mounted and only the selected one is visible,
   * so the cell is as tall as the tallest panel and the sheet around the tabs
   * stops changing height — and jumping on screen — with every tab. Needs a
   * `TabsPanels` parent. The hidden panels are `invisible`, so they leave the
   * tab order and the accessibility tree the way an unmounted panel would.
   */
  stacked?: boolean;
}

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  TabsContentProps
>(({ className, stacked, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    forceMount={stacked ? true : undefined}
    className={cn(
      "mt-2 ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
      // `block` outranks the `hidden` attribute Radix puts on a force-mounted
      // inactive panel; `invisible` is what actually hides it.
      stacked &&
        "col-start-1 row-start-1 data-[state=inactive]:block data-[state=inactive]:invisible",
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

/** The grid that `TabsContent stacked` panels share. */
const TabsPanels = ({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("grid", className)} {...props} />
);

export { Tabs, TabsList, TabsTrigger, TabsContent, TabsPanels };
