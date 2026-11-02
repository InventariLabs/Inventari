import type { SlotDataMap } from "@/lib/moduleRegistry";
import ReplenishSuggestionsModal from "../ReplenishSuggestionsModal";

type Props = { data: SlotDataMap["dashboard_replenish_modal"] };

export default function ReplenishSuggestionsModalSlot({ data }: Props) {
  return (
    <ReplenishSuggestionsModal isOpen={data.isOpen} onClose={data.onClose} />
  );
}
