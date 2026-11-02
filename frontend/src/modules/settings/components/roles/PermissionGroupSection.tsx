import { ChevronDown } from "lucide-react";
import { Checkbox } from "@/components/ui/Checkbox";
import { cn } from "@/lib/utils";
import type { PermissionDefinition } from "@/modules/settings/hooks/useRoles";
import {
  groupState,
  matchPermissions,
  type PermissionGroup,
} from "./rolePermissions";

interface PermissionGroupSectionProps {
  group: PermissionGroup;
  label: string;
  granted: ReadonlySet<string>;
  readOnly: boolean;
  expanded: boolean;
  search: string;
  onToggleExpanded: () => void;
  onToggle: (key: string) => void;
  onToggleAll: (keys: string[], next: boolean) => void;
  labelOf: (permission: PermissionDefinition) => string;
  descriptionOf: (permission: PermissionDefinition) => string | null;
  countLabel: (held: number, total: number) => string;
}

/**
 * One module's permissions, collapsed until asked for.
 *
 * The screen this replaced put every permission of every installed module on
 * one axis of a table — thirty-three columns with nine modules enabled, and one
 * more for every module installed after. Sections turn that growth from
 * horizontal scrolling into vertical, which the reader already knows how to do.
 */
export function PermissionGroupSection({
  group,
  label,
  granted,
  readOnly,
  expanded,
  search,
  onToggleExpanded,
  onToggle,
  onToggleAll,
  labelOf,
  descriptionOf,
  countLabel,
}: PermissionGroupSectionProps) {
  const visible = matchPermissions(group.permissions, search, labelOf);
  if (visible.length === 0) return null;

  const state = groupState(group, granted);
  const held = group.permissions.filter((p) => granted.has(p.key)).length;
  // A search puts the reader past the point of browsing — they named the thing
  // they want, so every section that still has a match is open.
  const isOpen = expanded || search.trim().length > 0;

  return (
    <section className="border border-border rounded-lg overflow-hidden">
      <div className="flex items-center gap-3 bg-surface-raised px-3 py-2.5">
        <Checkbox
          checked={state === "all"}
          indeterminate={state === "some"}
          disabled={readOnly}
          onChange={() =>
            onToggleAll(
              group.permissions.map((p) => p.key),
              state !== "all",
            )
          }
          aria-label={label}
        />
        {/* eslint-disable-next-line no-restricted-syntax -- full-width disclosure row beside its checkbox, not a chrome button; Button variants would impose padding/height/rounding on the section header */}
        <button
          type="button"
          onClick={onToggleExpanded}
          aria-expanded={isOpen}
          className="flex flex-1 items-center justify-between gap-2 min-w-0 text-left"
        >
          <span className="text-sm font-medium text-on truncate">{label}</span>
          <span className="flex items-center gap-2 shrink-0">
            <span className="text-xs text-on-muted tabular-nums">
              {countLabel(held, group.permissions.length)}
            </span>
            <ChevronDown
              size={16}
              aria-hidden
              className={cn(
                "text-on-muted transition-transform",
                isOpen && "rotate-180",
              )}
            />
          </span>
        </button>
      </div>

      {isOpen && (
        <ul className="divide-y divide-border/60">
          {visible.map((permission) => {
            const description = descriptionOf(permission);
            return (
              <li key={permission.key} className="px-3 py-2.5">
                <label
                  className={cn(
                    "flex items-start gap-3",
                    readOnly ? "cursor-not-allowed" : "cursor-pointer",
                  )}
                >
                  <Checkbox
                    className="mt-0.5"
                    checked={granted.has(permission.key)}
                    disabled={readOnly}
                    onChange={() => onToggle(permission.key)}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm text-on">
                      {labelOf(permission)}
                    </span>
                    {description && (
                      <span className="block text-xs text-on-muted mt-0.5">
                        {description}
                      </span>
                    )}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
