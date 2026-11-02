import { useCallback, useRef, type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import {
  PackagePlus,
  PackageMinus,
  ArrowLeftRight,
  ArrowDownToLine,
  ArrowUpFromLine,
  Trash2,
  Plus,
} from "lucide-react";

import { Button } from "@/components/ui/Button";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import { documentTypeName } from "@/modules/warehouse/lib/documentTypeName";
import type { DocumentType } from "@/modules/warehouse/types";

const NEW_DOC_ACTIONS: Array<{
  type: DocumentType;
  icon: typeof PackagePlus;
}> = [
  { type: "IN", icon: PackagePlus },
  { type: "OUT", icon: PackageMinus },
  { type: "INT", icon: ArrowLeftRight },
  { type: "INTERNAL_IN", icon: ArrowDownToLine },
  { type: "INTERNAL_OUT", icon: ArrowUpFromLine },
  { type: "SCRAP", icon: Trash2 },
];

/**
 * Every type this menu offers, in menu order. The History panel describes
 * the menu for the reader, and a description written by hand beside it
 * drifts: it listed PZ, WZ, MM, PW and RW while the menu also offered a
 * write-off, so the panel promised five documents and the menu made six.
 */
export const NEW_DOCUMENT_TYPES: readonly DocumentType[] = NEW_DOC_ACTIONS.map(
  (action) => action.type,
);

interface NewDocumentMenuProps {
  onSelect: (type: DocumentType) => void;
  /** A control of the caller's own that opens the menu, in place of the
   *  header button. It must forward its ref and take a click. */
  trigger?: ReactElement;
}

/**
 * The "New document" type picker.
 *
 * It looks like a menu, so it has to behave like one: the popover carries
 * `role="menu"`, each option is a `menuitem`, and the arrow keys walk the
 * list. As a bare popover full of buttons, a screen reader announced a group
 * of buttons and the arrow keys did nothing at all.
 */
export function NewDocumentMenu({ onSelect, trigger }: NewDocumentMenuProps) {
  const { t } = useTranslation("warehouse");
  const { data: profile } = useDocumentProfile();
  const itemsRef = useRef<(HTMLButtonElement | null)[]>([]);

  const focusItem = useCallback((index: number) => {
    const items = itemsRef.current.filter(Boolean) as HTMLButtonElement[];
    if (items.length === 0) return;
    const wrapped = (index + items.length) % items.length;
    items[wrapped]?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const items = itemsRef.current.filter(Boolean) as HTMLButtonElement[];
      const current = items.indexOf(
        document.activeElement as HTMLButtonElement,
      );
      if (event.key === "ArrowDown") {
        event.preventDefault();
        focusItem(current + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        focusItem(current - 1);
      } else if (event.key === "Home") {
        event.preventDefault();
        focusItem(0);
      } else if (event.key === "End") {
        event.preventDefault();
        focusItem(items.length - 1);
      }
    },
    [focusItem],
  );

  return (
    <PopoverPrimitive.Root>
      <PopoverPrimitive.Trigger asChild>
        {trigger ?? (
          <Button size="sm" leftIcon={<Plus size={16} />} aria-haspopup="menu">
            {t("newDocument")}
          </Button>
        )}
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          role="menu"
          aria-label={t("newDocument")}
          onKeyDown={handleKeyDown}
          className="z-[var(--z-popover)] w-56 bg-surface-card rounded-xl border border-border shadow-xl p-1 flex flex-col gap-1"
          sideOffset={4}
        >
          {NEW_DOC_ACTIONS.map(({ type, icon: Icon }, index) => (
            <PopoverPrimitive.Close asChild key={type}>
              <Button
                ref={(node) => {
                  itemsRef.current[index] = node;
                }}
                role="menuitem"
                variant="ghost"
                size="sm"
                className="w-full justify-start gap-2"
                onClick={() => onSelect(type)}
              >
                <Icon size={16} />
                {documentTypeName(t, type, profile?.type_labels?.[type])}
              </Button>
            </PopoverPrimitive.Close>
          ))}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
