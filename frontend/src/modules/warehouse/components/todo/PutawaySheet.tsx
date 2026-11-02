import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { LocationField } from "@/modules/warehouse/components/LocationField";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useScanResolver } from "@/hooks/useScanResolver";
import { useLocationsById } from "@/module-sdk";
import { ShelfSelect } from "@/modules/warehouse/components/LineTargetPicker";
import {
  locationChoiceOf,
  type LocationChoice,
} from "@/modules/warehouse/locationChoices";
import { usePutAwayWorkItem } from "@/modules/warehouse/hooks/useWorkItems";
import type { WorkItem } from "@/modules/warehouse/types";
import FloorShelf, {
  type FloorShelfPlace,
} from "@/modules/warehouse/components/FloorShelf";
import ScanField from "@/modules/warehouse/components/ScanField";
import ShelfConfirmation, {
  type ShelfConfirmationState,
} from "@/modules/warehouse/components/ShelfConfirmation";
import type { HomeShelfOffer } from "@/modules/warehouse/api/putaway";
import { HomeShelfPrompt } from "./HomeShelfPrompt";
import { workItemSentence } from "./workItemText";

/** Below `sm` the tasks are worked one at a time, as a phone holds them. */
const PHONE_QUERY = "(max-width: 639px)";

/**
 * Why the task names this shelf, in the reader's words: a rule wrote it
 * down, the product already stands there, or it is the shelf the last move
 * into this warehouse used. Empty when nothing named one.
 */
function shelfReason(
  t: (key: string) => string,
  source: string | null | undefined,
): string | null {
  switch (source) {
    case "rule":
      return t("todo.putawaySheet.reason.rule");
    case "stock":
      return t("todo.putawaySheet.reason.stock");
    case "zone":
      return t("todo.putawaySheet.reason.zone");
    default:
      return null;
  }
}

/** The shelf the card must read, from the task's own offer or the worker's pick. */
function floorPlace(
  task: WorkItem,
  chosenId: string,
  choice: LocationChoice | undefined,
): FloorShelfPlace | null {
  if (!chosenId) return null;
  return {
    code:
      choice?.code ??
      (chosenId === task.place_id ? task.place_code : null) ??
      null,
    name:
      choice?.name ??
      (chosenId === task.place_id ? task.place : null) ??
      choice?.path ??
      "",
  };
}

/**
 * The phone's step: the shelf card, the scan that confirms the worker stands
 * there when the profile asks for one, and the chooser for carrying the goods
 * elsewhere. A desktop keeps the whole location list instead.
 */
function PhoneShelfStep({
  chosenId,
  place,
  reason,
  confirmation,
  choosing,
  scanRequired,
  posting,
  onScan,
  onChoose,
  onCancel,
  onPick,
}: {
  chosenId: string;
  place: FloorShelfPlace | null;
  reason: string | null;
  confirmation: ShelfConfirmationState | null;
  choosing: boolean;
  scanRequired: boolean;
  posting: boolean;
  onScan: (code: string) => void;
  onChoose: () => void;
  onCancel: () => void;
  onPick: (locationId: string | null) => void;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <>
      <FloorShelf
        label={t("todo.putawaySheet.putOn")}
        shelf={place}
        reason={reason}
        confirmation={confirmation}
        kind="receiving"
        onChoose={onChoose}
      />
      {scanRequired && place && !choosing && confirmation !== "confirmed" && (
        <ScanField
          prompt={t("receiving.phone.scanLocation")}
          disabled={posting}
          onCode={onScan}
        />
      )}
      {choosing && (
        <div className="space-y-2">
          <ShelfSelect
            value={chosenId || null}
            placeholder={t("floorShelf.choose")}
            onChange={onPick}
          />
          <Button variant="ghost" className="w-full" onClick={onCancel}>
            {t("common:form.cancel")}
          </Button>
        </div>
      )}
      {!choosing && place && (
        <Button variant="ghost" className="w-full" onClick={onChoose}>
          {t("todo.putawaySheet.elsewhere")}
        </Button>
      )}
    </>
  );
}

/** The desktop's confirmation, when the profile asks for the label's scan. */
function DesktopShelfConfirmation({
  chosenId,
  place,
  state,
  posting,
  onScan,
}: {
  chosenId: string;
  place: FloorShelfPlace | null;
  state: ShelfConfirmationState | null;
  posting: boolean;
  onScan: (code: string) => void;
}) {
  const { t } = useTranslation("warehouse");
  if (!chosenId || !place || !state) return null;
  return (
    <div className="space-y-2">
      {state !== "confirmed" && (
        <ScanField
          prompt={t("receiving.phone.scanLocation")}
          disabled={posting}
          onCode={onScan}
        />
      )}
      <ShelfConfirmation state={state} kind="receiving" />
    </div>
  );
}

/**
 * Putting away one task: the shelf the rules suggest, already chosen, and the
 * one button that posts the move. The person carrying the goods may name
 * another shelf — the one with room, the one they are standing at — and a
 * task the rules had no shelf for asks for one before it can be done.
 *
 * On a phone the shelf is the step: the code large as it is printed on the
 * label, the name under it and why, and posting the task moves to the next
 * one waiting, so the person carries goods shelf after shelf without going
 * back to the list. A desktop keeps the list of every location in the sheet.
 *
 * The order is fixed when the sheet opens, the tasks in it are not: each
 * step reads the task as the list now reports it, so a carry just posted
 * can offer the next task the shelf it made the last one used.
 */
export function PutawaySheet({
  item,
  queue,
  onClose,
}: {
  item: WorkItem;
  /** The put-away tasks in the order the list shows them, this one included. */
  queue: WorkItem[];
  onClose: () => void;
}) {
  const { t } = useTranslation("warehouse");
  const isPhone = useMediaQuery(PHONE_QUERY);
  // Only the order is fixed: a task posted while the worker walks to the
  // next shelf must not renumber the step under their thumb, but the tasks
  // themselves stay the list's — their shelf offer is read after every post.
  const [order] = useState(() => {
    const all = queue.filter((task) => task.next_action === "put_away");
    const at = all.findIndex((task) => task.key === item.key);
    return at < 0 ? [item.key] : all.slice(at).map((task) => task.key);
  });
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<Record<string, string>>({});
  /** Per task, the shelf label the worker scanned and what it named. */
  const [scanned, setScanned] = useState<
    Record<string, { code: string; locationId: string }>
  >({});
  const [choosing, setChoosing] = useState(false);
  /** The home-location question a posted carry raised, with the step it holds up. */
  const [asking, setAsking] = useState<{
    offer: HomeShelfOffer;
    proceed: () => void;
  } | null>(null);
  const live = useMemo(
    () =>
      new Map(
        queue
          .filter((task) => task.next_action === "put_away")
          .map((task) => [task.key, task]),
      ),
    [queue],
  );
  // A task that left the list between two steps is skipped, not shown stale,
  // and when none of the rest is left the walk is over: the task the sheet
  // opened on was posted (or done elsewhere) and must not come back to post.
  const foundAt = order.findIndex((key, position) => {
    return position >= index && live.has(key);
  });
  const exhausted = foundAt < 0;
  const at = exhausted ? Math.min(index, order.length - 1) : foundAt;
  const task = live.get(order[at]) ?? item;
  // The carry just posted leaves the list; its question is still to be answered.
  useEffect(() => {
    if (exhausted && !asking) onClose();
  }, [exhausted, asking, onClose]);
  const putAway = usePutAwayWorkItem();

  const chosenId = picked[task.key] ?? task.place_id ?? "";
  // The shelf the card names is read by id: the walk never needs the list.
  const { byId: chosenPlace, isError: treeFailed } = useLocationsById([
    chosenId,
  ]);
  const chosen = chosenPlace.get(chosenId);
  const place = floorPlace(task, chosenId, chosen && locationChoiceOf(chosen));
  const reason =
    place && chosenId === task.place_id
      ? shelfReason(t, task.place_source)
      : null;
  const scanRequired = task.shelf_scan_required === true;
  const scan = scanned[task.key];
  const confirmedShelfId =
    scan && scan.locationId === chosenId ? scan.locationId : null;
  const confirmation: ShelfConfirmationState | null =
    scanRequired && place ? (confirmedShelfId ? "confirmed" : "toScan") : null;

  const { resolve } = useScanResolver({
    handle: (result, code) => {
      // Anything else scanned here is answered here: the offer to open it on
      // another screen would walk away from the carry.
      if (result.action === "set_storage_context" && result.location) {
        const found = result.location;
        if (found.id !== chosenId) {
          toast.error(
            t("receiving.toast.wrong_shelf", {
              location: place?.code || place?.name || "",
            }),
          );
          return true;
        }
        setScanned((prev) => ({
          ...prev,
          [task.key]: { code, locationId: found.id },
        }));
        return true;
      }
      toast.error(t("receiving.phone.notALocation"));
      return true;
    },
    acceptUnrecognized: () => {
      toast.error(t("receiving.phone.notALocation"));
      return true;
    },
  });

  const choose = (locationId: string | null) => {
    setPicked((prev) => ({ ...prev, [task.key]: locationId ?? "" }));
    setChoosing(false);
  };

  const submit = () => {
    if (scanRequired && !confirmedShelfId) return;
    putAway.mutate(
      {
        lineId: task.source_id,
        locationId: chosenId,
        ...(confirmedShelfId && scan ? { scannedCode: scan.code } : {}),
      },
      {
        onSuccess: (moved) => {
          // A move the profile sends for approval is posted by the approval.
          toast.success(
            moved.status === "PENDING_APPROVAL"
              ? t("todo.putawaySheet.awaitingApproval", {
                  number: moved.number,
                })
              : t("todo.putawaySheet.done", { number: moved.number }),
          );
          const proceed = () => {
            if (isPhone && at + 1 < order.length) {
              setIndex(at + 1);
              setChoosing(false);
              return;
            }
            onClose();
          };
          if (moved.home_shelf) {
            setAsking({ offer: moved.home_shelf, proceed });
            return;
          }
          proceed();
        },
      },
    );
  };

  if (asking) {
    return (
      <HomeShelfPrompt
        offer={asking.offer}
        isPhone={isPhone}
        onDone={() => {
          setAsking(null);
          asking.proceed();
        }}
      />
    );
  }

  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal"
      maxWidth="sm"
      fullBleedOnMobile={isPhone}
      aria-label={t("todo.putawaySheet.title")}
    >
      <SheetHeader title={t("todo.putawaySheet.title")} onClose={onClose} />
      <SheetBody className="space-y-4 p-5">
        {isPhone && order.length > 1 && (
          <p className="text-sm text-on-secondary" aria-live="polite">
            {t("todo.putawaySheet.step", {
              current: at + 1,
              total: order.length,
            })}
          </p>
        )}
        <p className="text-sm text-on">{workItemSentence(t, task)}</p>

        {isPhone ? (
          <PhoneShelfStep
            chosenId={chosenId}
            place={place}
            reason={reason}
            confirmation={confirmation}
            choosing={choosing}
            scanRequired={scanRequired}
            posting={putAway.isPending}
            onScan={(code) => void resolve(code)}
            onChoose={() => setChoosing(true)}
            onCancel={() => setChoosing(false)}
            onPick={choose}
          />
        ) : (
          <>
            <LocationField
              label={t("todo.putawaySheet.location")}
              scope={{ purpose: "stock" }}
              value={chosenId}
              onChange={(id) => choose(id || null)}
              placeholder={t("todo.putawaySheet.chooseLocation")}
              searchPlaceholder={t("receive.searchWarehouse")}
              title={t("todo.putawaySheet.location")}
              clearable
              clearLabel={t("todo.putawaySheet.chooseLocation")}
            />
            <DesktopShelfConfirmation
              chosenId={chosenId}
              place={place}
              state={confirmation}
              posting={putAway.isPending}
              onScan={(code) => void resolve(code)}
            />
          </>
        )}
        {treeFailed && (
          <p role="alert" className="text-sm text-on-warning">
            {t("start.warehouse.failed")}
          </p>
        )}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onClose}>
            {t("common:actions.cancel")}
          </Button>
          <Button
            onClick={submit}
            disabled={
              !chosenId ||
              putAway.isPending ||
              (scanRequired && !confirmedShelfId)
            }
          >
            {t("todo.putAway")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
