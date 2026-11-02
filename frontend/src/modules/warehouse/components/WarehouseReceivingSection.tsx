import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { QueryFailure } from "@/components/ui/QueryResult";
import { usePageSavePart } from "@/module-sdk";
import { useStoragesTree } from "@/hooks/queries/useStoragesTree";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import {
  useReceivingModes,
  useSetReceivingMode,
} from "@/modules/warehouse/hooks/usePutawayRules";
import { SettingsSectionHeader } from "./SettingsSectionHeader";

/** What a pick changes for one warehouse; a key left out stays as stored. */
type Pick = { twoStep?: boolean; freePlacement?: boolean };

/**
 * How each warehouse receives: in one go, onto the shelf the rules choose,
 * or into its receiving area with the putaway left to somebody else as
 * tasks in To do. A warehouse is a top-level location; one that never chose
 * receives in one step.
 *
 * Under a warehouse that puts away later, whether it keeps a place per
 * product: where it does (the default), putting goods away on a different
 * location asks whether it is now the product's home; a warehouse that
 * stores wherever there is room is never asked. Receiving in one step has
 * no put-away to ask in, so the choice is not offered there.
 */
export function WarehouseReceivingSection({ canWrite }: { canWrite: boolean }) {
  const { t } = useTranslation("warehouse");
  const excludeModuleContexts = !useShowModuleData();
  // Only the warehouses (the top of the tree) are drawn here, and no number.
  const { data: warehouses } = useStoragesTree(undefined, {
    excludeModuleContexts,
    depth: 1,
    counts: false,
  });
  const { data: modes, isError, error, refetch } = useReceivingModes();
  const setMode = useSetReceivingMode();

  // Picks wait for the page's Save: warehouse id -> what was chosen, only for
  // the choices that differ from what is stored.
  const [picked, setPicked] = useState<Record<string, Pick>>({});
  const byWarehouse = new Map(
    (modes ?? []).map((mode) => [mode.warehouse_id, mode]),
  );
  const pending = Object.entries(picked).flatMap(([warehouseId, pick]) => {
    const stored = byWarehouse.get(warehouseId);
    const changes: Pick = {};
    if (
      pick.twoStep !== undefined &&
      pick.twoStep !== (stored?.two_step ?? false)
    )
      changes.twoStep = pick.twoStep;
    if (
      pick.freePlacement !== undefined &&
      pick.freePlacement !== (stored?.free_placement ?? false)
    )
      changes.freePlacement = pick.freePlacement;
    return Object.keys(changes).length > 0 ? [{ warehouseId, ...changes }] : [];
  });

  const save = async () => {
    for (const change of pending) {
      await setMode.mutateAsync(change);
    }
    setPicked({});
  };
  usePageSavePart("receivingModes", pending.length > 0, save);

  if (!warehouses || warehouses.length === 0) return null;

  const choose = (warehouseId: string, pick: Pick) =>
    setPicked((current) => ({
      ...current,
      [warehouseId]: { ...current[warehouseId], ...pick },
    }));

  return (
    <Card className="p-4">
      <SettingsSectionHeader
        title={t("putaway.receiving.title")}
        hint={t("putaway.receiving.hint")}
      />
      {isError ? (
        <QueryFailure
          error={error}
          message={t("putaway.receiving.loadFailed")}
          onRetry={() => refetch()}
        />
      ) : (
        <ul className="divide-y divide-border">
          {warehouses.map((warehouse) => {
            const mode = byWarehouse.get(warehouse.id);
            const twoStep =
              picked[warehouse.id]?.twoStep ?? mode?.two_step ?? false;
            const freePlacement =
              picked[warehouse.id]?.freePlacement ??
              mode?.free_placement ??
              false;
            return (
              <li
                key={warehouse.id}
                className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3"
              >
                <div className="min-w-0 flex-1">
                  <span className="font-medium text-on break-words">
                    {warehouse.name}
                  </span>
                  {twoStep && mode?.receiving_location_name && (
                    <p className="text-xs text-on-secondary">
                      {t("putaway.receiving.landsIn", {
                        area: mode.receiving_location_name,
                      })}
                    </p>
                  )}
                </div>
                <NativeSelect
                  aria-label={t("putaway.receiving.modeFor", {
                    location: warehouse.name,
                  })}
                  wrapperClassName="w-full sm:w-80"
                  value={twoStep ? "two" : "one"}
                  disabled={!canWrite || modes === undefined}
                  onChange={(e) =>
                    choose(warehouse.id, { twoStep: e.target.value === "two" })
                  }
                >
                  <option value="one">{t("putaway.receiving.oneStep")}</option>
                  <option value="two">{t("putaway.receiving.twoStep")}</option>
                </NativeSelect>
                {twoStep && (
                  <div className="w-full">
                    <Checkbox
                      id={`fixed-places-${warehouse.id}`}
                      label={t("putaway.receiving.fixedPlaces", {
                        location: warehouse.name,
                      })}
                      checked={!freePlacement}
                      disabled={!canWrite || modes === undefined}
                      onChange={(e) =>
                        choose(warehouse.id, {
                          freePlacement: !e.target.checked,
                        })
                      }
                    />
                    <p className="ml-6 text-xs text-on-secondary">
                      {t("putaway.receiving.fixedPlacesHint")}
                    </p>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
