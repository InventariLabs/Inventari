import { useState } from "react";
import { LocationCombobox } from "@/module-sdk";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import {
  EmployeeAutocomplete,
  type CheckoutPerson,
} from "@/modules/equipment/components/EmployeeAutocomplete";
import { SELECTABLE_STATUSES } from "@/modules/equipment/components/AssetStatusBadge";

interface BulkEditDialogsProps {
  action: "change_status" | "change_location" | "assign_to";
  /**
   * How many assets the action reaches. The bar says it too, but the bar
   * scrolls away and the dialog is the last thing read before Apply — the
   * three confirmation dialogs on the same bar name the count in their
   * titles, and these three read the same at one selection as at three.
   */
  selectedCount: number;
  onConfirm: (action: string, data: Record<string, unknown>) => void;
  onCancel: () => void;
  isPending: boolean;
}

export function BulkEditDialogs({
  action,
  selectedCount,
  onConfirm,
  onCancel,
  isPending,
}: BulkEditDialogsProps) {
  const { t } = useTranslation("equipment");
  const [status, setStatus] = useState("AVAILABLE");
  const [locationId, setLocationId] = useState("");
  const [selectedPerson, setSelectedPerson] = useState<CheckoutPerson | null>(
    null,
  );

  const handleSubmit = () => {
    if (action === "change_status") {
      onConfirm("change_status", { status });
    } else if (action === "change_location") {
      onConfirm("change_location", { location_id: locationId });
    } else if (action === "assign_to") {
      // The same shape the single checkout sends: a partner pick carries
      // its id, an account pick carries the email the holder is matched
      // by. Sending only the partner id made every batch-issued asset
      // invisible in "My assets" — the email was never stored.
      onConfirm("assign_to", {
        partner_id: selectedPerson?.partner?.id ?? null,
        assigned_to_name: selectedPerson?.name ?? "",
        assigned_to_email: selectedPerson?.email || null,
      });
    }
  };

  const titles: Record<string, string> = {
    change_status: t(
      "bulk_edit.change_status_title",
      "Change status of {{count}} assets",
      { count: selectedCount },
    ),
    change_location: t(
      "bulk_edit.change_location_title",
      "Move {{count}} assets to a location",
      { count: selectedCount },
    ),
    assign_to: t(
      "bulk_edit.assign_to_title",
      "Assign {{count}} assets to a person",
      { count: selectedCount },
    ),
  };

  return (
    <Dialog open onOpenChange={() => !isPending && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{titles[action]}</DialogTitle>
        </DialogHeader>

        {action === "change_status" && (
          <div className="space-y-3 py-4">
            {/* DEPLOYED/RETIRED are consequences, not choices — they are not
                offered here; the backend guards reject them anyway, but the
                picker should not propose what it cannot deliver. */}
            <Select
              label={t("bulk_edit.new_status", "New Status")}
              value={status}
              onChange={setStatus}
              options={SELECTABLE_STATUSES.map((s) => ({
                id: s,
                name: t(`status.${s.toLowerCase()}` as const),
              }))}
            />
          </div>
        )}

        {action === "change_location" && (
          <div className="space-y-3 py-4">
            {/* The module's own shelves, searched with their path: "Shelf A"
                standing in two rooms is one option repeated until the path
                says which room. */}
            <LocationCombobox
              label={t("bulk_edit.target_location", "Target Location")}
              scope={{ moduleScope: "equipment" }}
              value={locationId}
              onChange={setLocationId}
              placeholder={t(
                "bulk_edit.select_location",
                "Select location\u2026",
              )}
              title={t("bulk_edit.target_location", "Target Location")}
            />
          </div>
        )}

        {action === "assign_to" && (
          <div className="space-y-3 py-4">
            {/* The same registers the single checkout searches: the
                partners module AND the organization's own accounts. A
                member picked here has no partner row — the email is what
                connects the asset to them. */}
            <EmployeeAutocomplete
              label={t("bulk_edit.assign_to", "Assign to")}
              selected={selectedPerson}
              onSelect={setSelectedPerson}
              onClear={() => setSelectedPerson(null)}
              includeAccounts
            />
            {selectedPerson && !selectedPerson.email?.trim() && (
              // The trap the single checkout warns about, seen from the
              // picker side: "My assets" matches the holder by email, so
              // a person with no address on record never sees what this
              // batch just issued them. A signal, not a veto.
              <p className="text-xs text-on-warning">
                {t("bulk_edit.no_email_warning")}
              </p>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isPending}>
            {t("common:actions.cancel", "Cancel")}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={
              isPending ||
              (action === "change_location" && !locationId) ||
              (action === "assign_to" && !selectedPerson)
            }
          >
            {isPending && <Loader2 size={14} className="animate-spin mr-1" />}
            {t("common:actions.apply", "Apply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
