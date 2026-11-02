import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ScrollRow } from "@/components/ui/ScrollRow";
import { cn } from "@/lib/utils";

export interface ModuleStoreFilter<T extends string> {
  id: T;
  label: string;
}

interface ModuleStoreFiltersProps<T extends string> {
  filters: ModuleStoreFilter<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Names the filter set for a screen reader. */
  label: string;
}

// The chosen filter tints its background and keeps the label on `text-on`: a
// profile repaints the whole primary ramp, so brand-coloured text on a brand
// tint cannot be made safe here (UI_GUIDELINES, active/selected state).
const CHOSEN = "bg-primary-50 font-semibold text-on dark:bg-primary-900/30";
const UNCHOSEN = "text-on-secondary hover:bg-surface-raised hover:text-on";

/**
 * The store's filter set: a sidebar on a wide screen, a scrolling row of chips
 * on a narrow one.
 *
 * As a card either way, eight filters filled the whole first screen of a
 * 390×844 phone — so the first view of the platform's storefront contained no
 * modules at all.
 *
 * Each option says whether it is the chosen one. The state used to be carried
 * by the background colour alone, which a screen reader cannot see.
 */
export function ModuleStoreFilters<T extends string>({
  filters,
  value,
  onChange,
  label,
}: ModuleStoreFiltersProps<T>) {
  return (
    <>
      <nav aria-label={label} className="lg:hidden">
        <ScrollRow className="flex gap-2 [&>*]:shrink-0 [&>*]:whitespace-nowrap">
          {filters.map((filter) => (
            <Button
              key={filter.id}
              type="button"
              size="content"
              variant="outline"
              aria-pressed={value === filter.id}
              onClick={() => onChange(filter.id)}
              className={cn(
                "rounded-lg px-3 py-1.5 text-sm font-medium",
                value === filter.id ? CHOSEN : UNCHOSEN,
              )}
            >
              {filter.label}
            </Button>
          ))}
        </ScrollRow>
      </nav>

      <Card className="hidden lg:block p-2">
        <nav aria-label={label}>
          <ul className="space-y-0.5">
            {filters.map((filter) => (
              <li key={filter.id}>
                <Button
                  type="button"
                  size="content"
                  variant="ghost"
                  aria-pressed={value === filter.id}
                  onClick={() => onChange(filter.id)}
                  className={cn(
                    "w-full justify-start rounded-lg px-3 py-2 text-sm font-medium",
                    value === filter.id ? CHOSEN : UNCHOSEN,
                  )}
                >
                  {filter.label}
                </Button>
              </li>
            ))}
          </ul>
        </nav>
      </Card>
    </>
  );
}
