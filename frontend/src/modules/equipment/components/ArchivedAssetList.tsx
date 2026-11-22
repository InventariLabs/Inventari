import type { ArchivedItem } from "@/types";
import { ArchivedAssetRow } from "@/modules/equipment/components/ArchivedAssetRow";

interface ArchivedAssetListProps {
  items: ArchivedItem[];
  /** False drops the checkbox and both actions — a reader restores nothing. */
  selectable: boolean;
  selectedIds: Set<string>;
  isRestorePending: boolean;
  isPurgePending: boolean;
  onToggleSelect: (id: string) => void;
  onRestore: (id: string) => void;
  onPurge: (id: string) => void;
}

/** The archived tab's rows, one `ArchivedAssetRow` per retired asset. */
export function ArchivedAssetList({
  items,
  selectedIds,
  ...rowProps
}: ArchivedAssetListProps) {
  return (
    <div className="divide-y divide-border">
      {items.map((item) => (
        <ArchivedAssetRow
          key={item.id}
          item={item}
          isSelected={selectedIds.has(item.id)}
          {...rowProps}
        />
      ))}
    </div>
  );
}
