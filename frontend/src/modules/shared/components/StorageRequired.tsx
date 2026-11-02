import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { EyeOff, MapPin, Plus, Settings } from "lucide-react";
import type { StorageLocation } from "@/types";
import { Button } from "@/components/ui/Button";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import { useLocationOffer } from "@/module-sdk";
import type { LocationPickerPurpose } from "@/modules/shared/lib/locationPickerOffer";
import { NewLocationSheet } from "./NewLocationSheet";

interface StorageRequiredProps {
  /**
   * "screen" replaces the content of a page that cannot work without a
   * storage; "banner" sits above content that still works; "field" sits under
   * a form's storage picker that has nothing to offer — the form's task is to
   * save a record, so there the primary action creates the missing location
   * in place, even when existing ones are kept out of general lists (the
   * reader is told, so the choice is informed rather than a duplicate made
   * blind).
   */
  variant?: "screen" | "banner" | "field";
  /** Called after the first storage exists, with the storage just created. */
  onCreated?: (storage: StorageLocation) => void;
  /**
   * What the picker above this is for. It has to be the caller's answer, or
   * the two disagree: this component asks the same hook for the reason it
   * renders, and a stock flow that keeps a module's places out on purpose
   * must not be told — under its own empty picker — that a settings switch
   * would reveal them.
   */
  purpose?: LocationPickerPurpose;
}

/**
 * One answer to "you have nowhere to put this yet".
 *
 * Four screens used to enforce the same precondition four ways: a hard gate
 * sending the reader to the storage list, a warning banner, a modal with a
 * required field holding no options, and a call to action pointing at a form
 * with nothing to aim at. Each one interrupted the task and made the reader
 * find the create action a second time.
 *
 * Here the missing thing is named and created in place, so the task the reader
 * started survives.
 */
export function StorageRequired({
  variant = "screen",
  onCreated,
  purpose = "general",
}: StorageRequiredProps) {
  const { t } = useTranslation(["locations", "common"]);
  const navigate = useNavigate();
  const [sheetOpen, setSheetOpen] = useState(false);
  // A caller renders this component because *its* scoped list came back
  // empty; these two queries share that cache, so telling "nowhere" from
  // "hidden with the module's data" costs no request — and the distinction
  // comes from the same helper the pickers use, so a row the picker never
  // offers (a virtual counterpart, an archived shelf) is not mistaken for
  // one the policy is hiding. What each variant makes of the hidden case
  // differs on purpose: screen and banner withhold the create action
  // (offering "the first one" over live locations is how duplicates are
  // born), while field keeps it — next to the named cause, so the reader
  // creates a new location knowing others exist.
  //
  // The picker's own purpose travels with the question: a caller whose
  // picker keeps a module's places out on purpose gets a reason computed
  // the same way, or the note under its empty picker would offer a switch
  // that reveals nothing there.
  const { emptyReason } = useLocationOffer({ purpose });
  const hasHidden = emptyReason === "module-data-hidden";

  const openSheet = () => setSheetOpen(true);
  // The hash lands the reader on the module-data switch itself, not on the
  // top of a long settings page — SettingsGeneralSection scrolls to it.
  const openSettings = () => navigate("/settings#module-data");

  return (
    <>
      {variant === "field" ? (
        // Compact note under the picker it explains — never in place of the
        // form around it. Unlike the screen and banner variants, the hidden
        // case keeps the create action: the reader came to save a record,
        // and the message says plainly that other locations already exist.
        <div className="rounded-lg bg-amber-100 px-3 py-2 text-on-warning">
          <p className="flex items-start gap-2 text-xs font-medium">
            {hasHidden ? (
              <EyeOff size={14} className="shrink-0 mt-0.5" />
            ) : (
              <MapPin size={14} className="shrink-0 mt-0.5" />
            )}
            <span>
              {hasHidden
                ? t("locations:hidden.fieldHint")
                : t("locations:required.title")}
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-2 mt-2">
            <Button size="sm" onClick={openSheet} leftIcon={<Plus size={14} />}>
              {t("locations:required.action")}
            </Button>
            {hasHidden && (
              <Button size="sm" variant="ghost" onClick={openSettings}>
                {t("locations:hidden.openSettings")}
              </Button>
            )}
          </div>
        </div>
      ) : hasHidden ? (
        variant === "screen" ? (
          <EmptyState
            icon={EyeOff}
            title={t("locations:hidden.title")}
            description={t("locations:hidden.description")}
            primaryAction={
              <EmptyStateAction
                label={t("locations:hidden.openSettings")}
                onClick={openSettings}
                leftIcon={Settings}
              />
            }
          />
        ) : (
          <div className="flex items-center justify-between gap-3 rounded-xl bg-amber-100 px-4 py-3 text-on-warning">
            <p className="flex items-center gap-2 text-sm font-medium">
              <EyeOff size={16} className="shrink-0" />
              {t("locations:hidden.title")}
            </p>
            <Button size="sm" onClick={openSettings} className="shrink-0">
              {t("locations:hidden.openSettings")}
            </Button>
          </div>
        )
      ) : variant === "screen" ? (
        <EmptyState
          icon={MapPin}
          title={t("locations:required.title")}
          description={t("locations:required.description")}
          primaryAction={
            <EmptyStateAction
              label={t("locations:required.action")}
              onClick={openSheet}
              leftIcon={Plus}
            />
          }
        />
      ) : (
        <div className="flex items-center justify-between gap-3 rounded-xl bg-amber-100 px-4 py-3 text-on-warning">
          <p className="flex items-center gap-2 text-sm font-medium">
            <MapPin size={16} className="shrink-0" />
            {t("locations:required.title")}
          </p>
          <Button size="sm" onClick={openSheet} className="shrink-0">
            {t("locations:required.action")}
          </Button>
        </div>
      )}

      <NewLocationSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onCreated={onCreated}
      />
    </>
  );
}
