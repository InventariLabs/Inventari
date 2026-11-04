/**
 * Archiving a location: hides it from lists and pickers, relocating whatever
 * it holds in the same operation.
 *
 * This used to be a full-width button in the sheet footer that expanded into
 * its own picker. Archiving speaks about the record, not about the edit being
 * made, so the trigger moved to the header's `ActionMenu` and the question it
 * asks moved into a confirm dialog — the same place deleting already asked it.
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { getEveryPage } from "@/lib/api/client";
import { storagesApi } from "@/lib/api/storages";
import { useStoragesTree } from "@/hooks/queries/useStoragesTree";
import { flattenTree } from "@/modules/spaces/lib/storageTree";
import { LocationTargetPicker } from "./LocationTargetPicker";

interface Props {
  open: boolean;
  storageId: string;
  /**
   * How many locations stand directly inside. They are not archived with
   * their parent — they stay in the lists, at the top level — and the confirm
   * says so before the reader finds them there.
   */
  subLocations?: number;
  onOpenChange: (open: boolean) => void;
  onArchived: () => void;
}

export function StorageArchiveDialog({
  open,
  storageId,
  subLocations = 0,
  onOpenChange,
  onArchived,
}: Props) {
  const { t } = useTranslation(["locations", "common"]);
  // Putaway rules are the warehouse module's catalogue. Without that module
  // there is no catalogue to ask about, and the question went out anyway —
  // a 404 swallowed by the `.catch` below, once per opened dialog.
  const enabledModules = useEnabledModulesOptional();
  const hasDocuments = enabledModules.includes("warehouse");
  /**
   * Three states, not two. "Unknown" used to be folded into "empty", which
   * hid the target picker — and the backend then refused to archive a
   * location holding items, leaving the reader an error and nothing on the
   * screen to answer it with.
   */
  const [summary, setSummary] = useState<"loading" | "unknown" | number>(
    "loading",
  );
  const [targetId, setTargetId] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);

  // Active putaway rules naming this location or anything under it are
  // counted below, which needs the ids standing inside: read when the dialog
  // is open and the warehouse module is there to have rules.
  const inside = useStoragesTree(undefined, {
    parentId: storageId,
    depth: 20,
    counts: false,
    enabled: open && hasDocuments,
  });
  const subtree = useMemo(
    () =>
      new Set([storageId, ...flattenTree(inside.data ?? []).map((n) => n.id)]),
    [storageId, inside.data],
  );
  type PutawayRule = {
    is_active: boolean;
    target_location_id: string | null;
    // A rule walks an ordered list of shelves, and any one of them is
    // reason enough to speak up. `target_location_id` mirrors only the
    // head of that list, so counting by it alone hid every rule naming
    // this location second or later: the warning said "1" where two
    // rules pointed here, or stayed silent altogether.
    locations?: Array<{ location_id: string }>;
  };
  const [rules, setRules] = useState<PutawayRule[] | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setSummary("loading");
    setRules(null);
    setTargetId(null);
    storagesApi
      .getSummary(storageId)
      // Items in descendants count too — the backend relocates the whole
      // subtree, so a zone holding items only in child locations still
      // requires a move target.
      .then((result) => {
        if (!cancelled) setSummary(result.subtree_items_count);
      })
      .catch(() => {
        if (!cancelled) setSummary("unknown");
      });
    if (!hasDocuments) {
      return () => {
        cancelled = true;
      };
    }
    // The call goes through the plain API client on purpose — the rule
    // catalogue belongs to the warehouse module, and this question is the
    // storage's.
    getEveryPage<PutawayRule>("/warehouse/putaway-rules")
      .then((all) => {
        if (!cancelled) setRules(all);
      })
      .catch(() => {
        if (!cancelled) setRules(null);
      });
    return () => {
      cancelled = true;
    };
  }, [open, storageId, hasDocuments]);

  // The head field stays the fallback for a reader that predates the list —
  // an empty `locations` means the rule has only the one shelf.
  const shelvesOf = (r: PutawayRule) =>
    r.locations?.length
      ? r.locations.map((l) => l.location_id)
      : r.target_location_id
        ? [r.target_location_id]
        : [];
  // The warning is made only from a subtree that was read: with the places
  // inside missing it would count the rules naming this location alone and
  // call that the answer. Unknown says nothing, as it does when the rules
  // themselves could not be read.
  const putawayRulesCount =
    rules && !inside.isLoading && !inside.isError
      ? rules.filter(
          (r) => r.is_active && shelvesOf(r).some((id) => subtree.has(id)),
        ).length
      : null;

  const isUnknown = summary === "unknown";
  const needsTarget = typeof summary === "number" && summary > 0;
  // Unknown contents offer the picker without demanding it: an empty
  // location archives fine, and a full one at least has an answer here.
  const showTarget = needsTarget || isUnknown;

  // The rejection is deliberately left to travel: the dialog it sits in keeps
  // itself open on one and shows the reason inside, where the chosen target is
  // still on screen. Closing on failure looked exactly like success.
  const handleConfirm = async () => {
    setIsPending(true);
    try {
      await storagesApi.archive(storageId, targetId ?? undefined);
      toast.success(t("locations:messages.storageArchived"));
      onOpenChange(false);
      onArchived();
    } finally {
      setIsPending(false);
    }
  };

  return (
    <ConfirmDialog
      open={open}
      title={t("locations:edit.archiveTitle")}
      // The second sentence answers the question the first one raises: an
      // operation offered as the alternative to deletion has to say whether
      // it can be taken back, and where from.
      message={[
        `${
          isUnknown
            ? t("locations:edit.archiveConfirmUnknown")
            : needsTarget
              ? t("locations:edit.archiveConfirmItems")
              : t("locations:edit.archiveConfirmEmpty")
        } ${t("locations:edit.archiveReversible")}`,
        subLocations > 0
          ? t("locations:edit.archiveSubLocations", { count: subLocations })
          : null,
        putawayRulesCount
          ? t("locations:edit.archivePutawayRules", {
              count: putawayRulesCount,
            })
          : null,
      ]
        .filter(Boolean)
        .join(" ")}
      variant="danger"
      confirmLabel={t("locations:edit.archive")}
      // The summary decides whether a target is required, so until it lands
      // there is no way to know what confirming would do.
      confirmDisabled={
        isPending || summary === "loading" || (needsTarget && !targetId)
      }
      onConfirm={handleConfirm}
      errorFallback={t("locations:errors.cannotArchive")}
      onCancel={() => onOpenChange(false)}
    >
      {showTarget && (
        <LocationTargetPicker
          label={t("locations:edit.archiveTargetLabel")}
          value={targetId ?? ""}
          onChange={(id) => setTargetId(id || null)}
          excludeSubtreeOf={[storageId]}
          leavesOnly
          clearable
          clearLabel={t("locations:edit.archiveTargetNone")}
          placeholder={t("locations:edit.archiveTargetNone")}
          searchPlaceholder={t("common:search")}
          emptyMessage={t("common:noResults")}
          title={t("locations:edit.archiveTargetLabel")}
          layer="confirm"
        />
      )}
    </ConfirmDialog>
  );
}
