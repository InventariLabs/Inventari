import { useEffect, useRef, useState } from "react";
import { SheetActions } from "@/components/ui/Sheet";
import { useTranslation } from "react-i18next";
import { Loader2, Wrench } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { Textarea } from "@/components/ui/Textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/Dialog";
import { useCreateMaintenanceLog } from "@/modules/equipment/hooks/useEquipment";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { todayInZone } from "@/utils/zonedDay";
import { formatNumberLocale } from "@/utils/formatters";
import type { MaintenanceLogCreate } from "@/modules/equipment/api/equipment";

interface MaintenanceLogModalProps {
  itemId: string;
  itemName: string;
  /** The asset's current status; only an available one can be taken in. */
  status?: string | null;
  /** Moves the asset to Maintenance (the page's own status change). */
  onMarkInService?: () => void;
  onClose: () => void;
}

type MaintenanceType =
  "REPAIR" | "CLEANING" | "UPGRADE" | "INSPECTION" | "OTHER";

const TYPES: MaintenanceType[] = [
  "REPAIR",
  "CLEANING",
  "UPGRADE",
  "INSPECTION",
  "OTHER",
];

const TYPE_KEYS: Record<MaintenanceType, string> = {
  REPAIR: "maintenance.type_repair",
  CLEANING: "maintenance.type_cleaning",
  UPGRADE: "maintenance.type_upgrade",
  INSPECTION: "maintenance.type_inspection",
  OTHER: "maintenance.type_other",
};

export function MaintenanceLogModal({
  itemId,
  itemName,
  status,
  onMarkInService,
  onClose,
}: MaintenanceLogModalProps) {
  const { t } = useTranslation("equipment");
  const createMutation = useCreateMaintenanceLog();
  const orgCurrency = useOrganizationCurrency();

  const timezone = useOrganizationTimezone();
  const dateTouched = useRef(false);

  // No preselection. "Inspection" was the standing answer — the fourth chip
  // of five, and the one that says least about what was actually done — so
  // whoever filed quickly filed it, and the log filled up with inspections.
  const [form, setForm] = useState({
    maintenance_type: "" as MaintenanceType | "",
    title: "",
    description: "",
    cost: "",
    performed_at: todayInZone(timezone),
    performed_by: "",
    next_maintenance_at: "",
  });

  useEffect(() => {
    if (!dateTouched.current) {
      setForm((current) => ({
        ...current,
        performed_at: todayInZone(timezone),
      }));
    }
  }, [timezone]);

  // Save used to be disabled until all three required answers were in, and
  // said nothing about which one was missing — no toast, no text at the field,
  // no `aria-invalid`. The button is live now and answers on press.
  // A repair filed today on an asset that is still available leaves it
  // offered for hand-out; the status change was a separate step nobody was
  // told to take. Offer it here, on by default, and only when the repair is
  // happening now — a past repair is a record, not a reason to pull the asset.
  const [takeIn, setTakeIn] = useState(true);
  const offerTakeIn =
    Boolean(onMarkInService) &&
    status === "AVAILABLE" &&
    form.maintenance_type === "REPAIR" &&
    form.performed_at === todayInZone(timezone);

  const [missing, setMissing] = useState<Record<string, boolean>>({});

  const set = (field: keyof typeof form, value: string) => {
    if (field === "performed_at") dateTouched.current = true;
    setForm((prev) => ({ ...prev, [field]: value }));
    setMissing((prev) => (prev[field] ? { ...prev, [field]: false } : prev));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const gaps = {
      maintenance_type: !form.maintenance_type,
      title: !form.title.trim(),
      performed_at: !form.performed_at,
    };
    if (gaps.maintenance_type || gaps.title || gaps.performed_at) {
      setMissing(gaps);
      return;
    }
    setMissing({});

    const payload: MaintenanceLogCreate = {
      item_id: itemId,
      maintenance_type: form.maintenance_type as MaintenanceType,
      title: form.title.trim(),
      description: form.description || undefined,
      cost: form.cost ? Number(form.cost) : undefined,
      currency: orgCurrency,
      performed_at: form.performed_at,
      performed_by: form.performed_by || undefined,
      next_maintenance_at: form.next_maintenance_at || undefined,
    };

    createMutation.mutate(payload, {
      onSuccess: () => {
        if (offerTakeIn && takeIn) onMarkInService?.();
        onClose();
      },
    });
  };

  // Radix Dialog handles ESC, focus trap, scroll lock, and the
  // canonical z-index. autoFocus removed: Radix auto-focuses the first
  // focusable element on mount (the Title input here). The scroll contract is
  // retained: form body has min-h-0 flex-1 overflow-y-auto so the action
  // buttons always stay inside the viewport on small screens.
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="w-full max-w-md sm:max-w-lg lg:max-w-xl gap-0 p-0 rounded-t-3xl sm:rounded-2xl max-h-[90vh] flex flex-col overflow-hidden"
        data-testid="maintenance-modal-card"
      >
        <DialogHeader className="flex flex-row items-center gap-3 border-b border-border px-5 py-4">
          <Wrench size={18} className="text-amber-500" />
          <DialogTitle className="font-semibold text-on">
            {t("maintenance.add_log")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t("maintenance.add_log")}
          </DialogDescription>
        </DialogHeader>

        <div className="px-5 pt-3 pb-1">
          <p className="text-sm text-on-muted">{itemName}</p>
        </div>

        {/* noValidate: the browser's own check stopped an empty form at the
            title, in the browser's language and about the title alone, so
            the answer below — every missing one, at its field — never ran. */}
        <form
          data-testid="maintenance-modal-body"
          noValidate
          onSubmit={handleSubmit}
          className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 space-y-4 pt-3"
        >
          <ChoiceGroup
            label={t("maintenance.type_label", "Type")}
            required
            error={
              missing.maintenance_type
                ? t("maintenance.type_required")
                : undefined
            }
            value={form.maintenance_type}
            onChange={(id) => set("maintenance_type", id)}
            options={TYPES.map((type) => ({
              id: type,
              label: t(TYPE_KEYS[type]),
            }))}
          />

          <div>
            <Input
              label={t("maintenance.title_label", "Title")}
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              placeholder={t(
                "maintenance.title_placeholder",
                "e.g. Replaced thermal paste",
              )}
              required
              error={
                missing.title ? t("maintenance.title_required") : undefined
              }
            />
          </div>

          <div className="grid grid-cols-2 items-end gap-3">
            <div>
              <DateInput
                label={t("maintenance.performed_at")}
                value={form.performed_at}
                onChange={(e) => set("performed_at", e)}
                required
                error={
                  missing.performed_at
                    ? t("maintenance.performed_at_required")
                    : undefined
                }
              />
            </div>
            <div>
              <Input
                label={t("maintenance.cost")}
                type="number"
                min="0"
                step="0.01"
                value={form.cost}
                onChange={(e) => set("cost", e.target.value)}
                placeholder={formatNumberLocale(0, 2)}
                rightIcon={
                  orgCurrency ? (
                    <span className="text-on-muted text-xs">{orgCurrency}</span>
                  ) : undefined
                }
              />
            </div>
          </div>

          <div>
            <Input
              label={t("maintenance.performed_by")}
              value={form.performed_by}
              onChange={(e) => set("performed_by", e.target.value)}
              placeholder={t(
                "maintenance.technician_placeholder",
                "Technician name",
              )}
            />
          </div>

          <div>
            <DateInput
              label={t("maintenance.next_maintenance")}
              value={form.next_maintenance_at}
              onChange={(e) => set("next_maintenance_at", e)}
            />
          </div>

          <Textarea
            label={t("maintenance.description_label", "Description")}
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-border bg-surface-card text-on px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500 resize-none placeholder:text-on-muted"
          />

          {offerTakeIn && (
            <Checkbox
              id="maintenance-take-in"
              checked={takeIn}
              onChange={(e) => setTakeIn(e.target.checked)}
              label={t("maintenance.take_in_service")}
            />
          )}

          <SheetActions className="pt-1">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={createMutation.isPending}
            >
              {t("common:actions.cancel", "Cancel")}
            </Button>
            <Button type="submit" disabled={createMutation.isPending}>
              {createMutation.isPending && (
                <Loader2 size={14} className="animate-spin mr-2" />
              )}
              {t("common:actions.save", "Save")}
            </Button>
          </SheetActions>
        </form>
      </DialogContent>
    </Dialog>
  );
}
