// The form docs/FRONTEND_MODULE_GUIDE.md gives a module that offers a slot of
// its own, kept here so the type-check compiles it: slotAugmentation.test.tsx
// renders this slot and `tsc` fails when the recipe stops merging into
// SlotDataMap. `export {};` is what makes the file a module augmentation; a
// file without any top-level import or export is a script, and TypeScript
// then reads the block as a declaration that replaces slotProps.
export {};

declare module "@/lib/moduleRegistry/slotProps" {
  interface SlotDataMap {
    fixture_module_card_extra: { recordId: string };
  }
}
