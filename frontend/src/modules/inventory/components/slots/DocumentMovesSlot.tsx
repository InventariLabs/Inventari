/**
 * What this document did to stock — contributed to the Document detail page.
 *
 * The lines say what was expected and what was done, and this slot adds where
 * the goods went and which batch they came out of. Both facts are in the
 * ledger, keyed by the document.
 */
import { useTranslation } from "react-i18next";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import { RecentStockMoves } from "@/modules/inventory/components/moves/RecentStockMoves";
import { recordsMovements } from "@/modules/inventory/constants/movementModules";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";

/** States in which nothing can have moved yet, so there is nothing to say. */
const BEFORE_ANY_MOVEMENT = ["DRAFT", "PENDING_APPROVAL"];

type Props = { data: SlotDataMap["document_detail_extra"] };

export default function DocumentMovesSlot({ data }: Props) {
  const { t } = useTranslation(["inventory"]);
  const enabledModules = useEnabledModulesOptional();

  if (!recordsMovements(enabledModules)) return null;
  if (BEFORE_ANY_MOVEMENT.includes(data.documentStatus)) return null;

  return (
    <section>
      <h2 className="text-lg font-semibold text-on mb-4 px-1">
        {t("inventory:moves.documentHeading")}
      </h2>
      <RecentStockMoves
        filters={{ reference_type: "document", reference_id: data.documentId }}
        caption={t("inventory:moves.documentCaption")}
        emptyTitle={t("inventory:moves.empty.documentTitle")}
        emptyDescription={t(
          data.stockAlreadyApplied
            ? "inventory:moves.empty.documentRecordOnlyDescription"
            : "inventory:moves.empty.documentDescription",
        )}
      />
    </section>
  );
}
