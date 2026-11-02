import type { SlotDataMap } from "@/lib/moduleRegistry";
import ItemEditModal from "../ItemEditModal";

type Props = { data: SlotDataMap["storage_item_edit_modal"] };

export default function ItemEditModalSlot({ data }: Props) {
  return <ItemEditModal itemId={data.itemId} onClose={data.onClose} />;
}
