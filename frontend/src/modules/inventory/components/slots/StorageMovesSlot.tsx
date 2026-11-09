/**
 * What moved through this place — contributed to the Storage detail page.
 *
 * A slot, not an import: the ledger belongs to Inventory and the storage
 * page belongs to Spaces, and modules do not reach into each other
 * (backend/AGENTS.md §4). `storage_detail_extra` was declared for exactly this and
 * had no contributor until now.
 */
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { ArrowUpRight } from "lucide-react";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import { RecentStockMoves } from "@/modules/inventory/components/moves/RecentStockMoves";
import { recordsMovements } from "@/modules/inventory/constants/movementModules";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";

type Props = { data: SlotDataMap["storage_detail_extra"] };

export default function StorageMovesSlot({ data }: Props) {
  const { t } = useTranslation(["inventory"]);
  const enabledModules = useEnabledModulesOptional();

  // Nothing writes movements here, so the section would be a heading over an
  // empty state on every storage page in the organization.
  if (!recordsMovements(enabledModules)) return null;

  return (
    <section>
      {/* The products list above counts records; the shelves count stock, by
          batch and by what is already promised. One line rather than a
          second table: two lists of "what is here" on one page read as a
          contradiction even when they agree. */}
      <p className="mb-4 px-1">
        <Link
          to={`/inventory/stock?location=${data.storageId}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-on-primary hover:underline"
        >
          {t("inventory:stock.seeForLocation")}
          <ArrowUpRight size={14} aria-hidden="true" />
        </Link>
      </p>
      <h2 className="text-lg font-semibold text-on mb-4 px-1">
        {t("inventory:moves.locationHeading")}
      </h2>
      <RecentStockMoves
        filters={{ location_id: data.storageId }}
        caption={t("inventory:moves.locationCaption")}
        seeAll={{
          to: `/inventory/moves?location=${data.storageId}`,
          label: t("inventory:moves.seeFullLedger"),
        }}
        emptyTitle={t("inventory:moves.empty.locationTitle")}
        emptyDescription={t("inventory:moves.empty.locationDescription")}
      />
    </section>
  );
}
