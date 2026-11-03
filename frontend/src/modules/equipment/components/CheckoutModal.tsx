import { useId, useState } from "react";
import { SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Loader2, User, MapPin, Plus, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/Button";
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
import { cn } from "@/lib/utils";
import { instantInsideDay, todayInZone } from "@/utils/zonedDay";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { useCheckout } from "@/modules/equipment/hooks/useEquipment";
import { useRequestApproval } from "@/modules/equipment/hooks/useMyAssets";
import { extractApiError, extractApiErrorCode } from "@/lib/errors";
import { useModules } from "@/contexts/ModulesContext";
import { useAddressMatchesDirectory } from "@/modules/equipment/hooks/useAddressMatchesDirectory";
import { LocationCombobox } from "@/module-sdk";
import QuickAddLocationModal from "@/modules/equipment/components/QuickAddLocationModal";
import {
  EmployeeAutocomplete,
  type CheckoutPerson,
} from "@/modules/equipment/components/EmployeeAutocomplete";
import type { Item } from "@/types";
import type {
  AssignmentCreate,
  EquipmentAssignment,
} from "@/modules/equipment/api/equipment";

type CheckoutMode = "person" | "location";

type CheckoutForm = {
  assigned_to_name: string;
  assigned_to_email: string;
  checkout_location_id: string;
  expected_return_at: string;
  checkout_notes: string;
};

/** The checkout the dialog describes, as the API takes it. */
function checkoutBody(
  itemId: string,
  form: CheckoutForm,
  mode: CheckoutMode,
  selectedPerson: CheckoutPerson | null,
  orgTimezone: Parameters<typeof instantInsideDay>[1],
): AssignmentCreate {
  const person = mode === "person";
  return {
    item_id: itemId,
    assignee_partner_id: person
      ? (selectedPerson?.partner?.id ?? undefined)
      : undefined,
    assigned_to_name: person ? form.assigned_to_name.trim() : "",
    assigned_to_email: person ? form.assigned_to_email || undefined : undefined,
    checkout_location_id: person
      ? undefined
      : form.checkout_location_id || undefined,
    expected_return_at: form.expected_return_at
      ? instantInsideDay(form.expected_return_at, orgTimezone).toISOString()
      : undefined,
    checkout_notes: form.checkout_notes || undefined,
  };
}

/**
 * Under an approval workflow the dialog either checks out (and, refused for
 * want of an approval, offers the request from where the refusal is shown)
 * or asks for the approval of exactly this checkout: the holder and the
 * return date travel with the request, so the approver does not decide
 * blind and the approval covers this checkout only.
 */
type CheckoutPurpose = "checkout" | "request";

interface CheckoutModalProps {
  item: Item;
  onClose: () => void;
  /**
   * Called with the assignment the server created, before the modal closes.
   *
   * The handover is the moment the protocol is worth offering -- somebody is
   * still standing at the desk. The offer cannot live in here, because this
   * component unmounts on the next line and a mutation fired from an
   * unmounted hook runs its callbacks nowhere. So the page that outlives the
   * modal gets told, and makes the offer.
   */
  onDone?: (assignment: EquipmentAssignment) => void;
  purpose?: CheckoutPurpose;
}

/** The refusal for want of an approval, with the request it calls for. */
function ApprovalNeededNotice({
  message,
  pending,
  onRequest,
}: {
  message: string;
  pending: boolean;
  onRequest: () => void;
}) {
  const { t } = useTranslation("equipment");
  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-on-warning dark:border-amber-500/20 dark:bg-amber-500/10"
    >
      <p>{message}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-2"
        leftIcon={<ShieldCheck size={14} />}
        onClick={onRequest}
        disabled={pending}
      >
        {t("approvals.request_this_checkout")}
      </Button>
    </div>
  );
}

/**
 * The one message slot under the email field: the consequence sentence while
 * the address is fine, the warning when it matches nobody.
 *
 * The warning is a distinct node (`key`) rather than the sentence relabelled,
 * so a screen reader meets it as an arrival — role="alert", the same way
 * every other form message in the app is announced. The consequence sentence
 * renders without a role: it is standing documentation of the field, not an
 * event, and must not speak every time the dialog opens.
 */
function EmailNotice({
  id,
  unmatched,
  empty,
}: {
  id: string;
  unmatched: boolean;
  empty: boolean;
}) {
  const { t } = useTranslation("equipment");
  if (unmatched) {
    return (
      <p
        key="warning"
        id={id}
        role="alert"
        className="mt-1 text-xs text-on-warning"
      >
        {t("assignments.checkout_modal.email_unmatched")}
      </p>
    );
  }
  return (
    <p
      key="hint"
      id={id}
      className={cn(
        "mt-1 text-xs",
        empty ? "text-on-warning" : "text-on-muted",
      )}
    >
      {t("assignments.checkout_modal.email_consequence")}
    </p>
  );
}

/**
 * The place a location checkout hands the asset to, searched on the server
 * as the reader types. A search that failed says so in the panel instead of
 * reading as an organization with no locations; adding a location stays
 * reachable beside it.
 */
function CheckoutLocationPicker({
  value,
  onChange,
  onAdd,
}: {
  value: string;
  onChange: (id: string) => void;
  onAdd: () => void;
}) {
  const { t } = useTranslation("equipment");
  return (
    <div className="flex items-end gap-2">
      <LocationCombobox
        label={t("assignments.checkout_modal.select_location", "Location")}
        wrapperClassName="flex-1"
        scope={{ contextTag: "equipment" }}
        value={value}
        onChange={onChange}
        placeholder={t("form.placeholders.location", "Select location…")}
        title={t("assignments.checkout_modal.select_location", "Location")}
      />
      <Button
        type="button"
        variant="outline"
        size="icon"
        onClick={onAdd}
        aria-label={t("locations.add", "Add")}
        title={t("locations.add", "Add")}
      >
        <Plus size={14} />
      </Button>
    </div>
  );
}

/**
 * The dialog's two buttons, outside the scroll layer so they hold their place
 * (UI_GUIDELINES §4.3): inside the form they sat wherever the form's end fell,
 * which on a phone was below the sheet's edge until the form was scrolled.
 * Submit reaches the form by its id. The refusal for want of an approval sits
 * here too, above the buttons: it holds the only way forward, so it must
 * appear where the finger was, not below the fold of the scrolling form.
 */
function CheckoutFooter({
  formId,
  asking,
  pending,
  approvalNeeded,
  onRequestApproval,
  incomplete,
  onClose,
}: {
  formId: string;
  asking: boolean;
  pending: boolean;
  approvalNeeded: string | null;
  onRequestApproval: () => void;
  incomplete: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation("equipment");
  return (
    <SheetFooter className="space-y-3">
      {approvalNeeded && (
        <ApprovalNeededNotice
          message={approvalNeeded}
          pending={pending}
          onRequest={onRequestApproval}
        />
      )}
      <SheetActions>
        <Button
          type="button"
          variant="outline"
          onClick={onClose}
          disabled={pending}
        >
          {t("common:actions.cancel", "Cancel")}
        </Button>
        <Button type="submit" form={formId} disabled={pending || incomplete}>
          {pending && <Loader2 size={14} className="animate-spin mr-2" />}
          {asking
            ? t("approvals.send_request")
            : t("assignments.checkout_modal.submit")}
        </Button>
      </SheetActions>
    </SheetFooter>
  );
}

export function CheckoutModal({
  item,
  onClose,
  onDone,
  purpose = "checkout",
}: CheckoutModalProps) {
  const { t } = useTranslation("equipment");
  const checkoutMutation = useCheckout();
  const requestMutation = useRequestApproval(item.id);
  // The refusal's own sentence, while the checkout waits for an approval.
  const [approvalNeeded, setApprovalNeeded] = useState<string | null>(null);
  const asking = purpose === "request";
  const pending = checkoutMutation.isPending || requestMutation.isPending;
  const { isModuleEnabled } = useModules();
  const partnersEnabled = isModuleEnabled("partners");
  // The day travels as an instant inside the organization's day, because
  // the backend reads arrivals through the org clock and pins the end of
  // the day it sees there: a browser-zone arrival stored the next day for
  // every org east of the reader (the write half of the same class as the
  // attestation deadline fix).
  const orgTimezone = useOrganizationTimezone();
  const orgToday = todayInZone(orgTimezone);

  const [mode, setMode] = useState<CheckoutMode>("person");
  const [showAddLocation, setShowAddLocation] = useState(false);

  const [selectedPerson, setSelectedPerson] = useState<CheckoutPerson | null>(
    null,
  );
  const [returnDateError, setReturnDateError] = useState("");
  const [form, setForm] = useState<CheckoutForm>({
    assigned_to_name: "",
    assigned_to_email: "",
    checkout_location_id: "",
    expected_return_at: "",
    checkout_notes: "",
  });

  const set = (field: keyof typeof form, value: string) => {
    if (
      selectedPerson &&
      (field === "assigned_to_name" || field === "assigned_to_email")
    ) {
      setSelectedPerson(null);
    }
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const addressUnmatched = useAddressMatchesDirectory({
    email: form.assigned_to_email.trim(),
    enabled: mode === "person" && !selectedPerson,
    partnersEnabled,
  });
  // The id the email field points at (`aria-describedby`), shared by the two
  // messages EmailNotice swaps between.
  const emailMessageId = useId();
  const formId = useId();

  const setReturnDate = (value: string) => {
    // component-level validation with an i18n message instead of a
    // native browser min attribute (which speaks the browser's language).
    // The floor is the organization's today: a reader west of the org
    // would otherwise be offered a day the org has already finished.
    setReturnDateError(
      value && value < orgToday
        ? t("assignments.checkout_modal.return_date_past_error")
        : "",
    );
    set("expected_return_at", value);
  };

  const send = (as: CheckoutPurpose) => {
    if (mode === "person" && !form.assigned_to_name.trim()) {
      toast.error(t("assignments.checkout_modal.error_person_required"));
      return;
    }
    if (mode === "location" && !form.checkout_location_id) {
      toast.error(t("form.errors.locationRequired", "Location is required"));
      return;
    }
    if (returnDateError) {
      toast.error(returnDateError);
      return;
    }

    const body = checkoutBody(item.id, form, mode, selectedPerson, orgTimezone);
    if (as === "request") {
      requestMutation.mutate(
        {
          assigned_to_name: body.assigned_to_name,
          assignee_partner_id: body.assignee_partner_id,
          checkout_location_id: body.checkout_location_id,
          expected_return_at: body.expected_return_at,
        },
        {
          onSuccess: () => {
            toast.success(t("approvals.requested"));
            onClose();
          },
          onError: (err) =>
            toast.error(extractApiError(err, t("approvals.request_error"))),
        },
      );
      return;
    }
    checkoutMutation.mutate(body, {
      onSuccess: (assignment) => {
        onDone?.(assignment);
        onClose();
      },
      onError: (err) => {
        const message = extractApiError(err, t("assignments.checkout_failed"));
        // Refused for want of an approval: the request is offered here, with
        // what was typed, instead of on the page behind the dialog.
        if (extractApiErrorCode(err) === "APPROVAL_REQUIRED") {
          setApprovalNeeded(message);
        } else {
          toast.error(message);
        }
      },
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    send(purpose);
  };

  // Radix Dialog handles ESC, focus trap, scroll lock, and the
  // canonical z-modal z-index. The nested QuickAddLocationModal is a
  // separate Radix Dialog instance; Radix manages stacking via its own
  // focus-management, no manual z-index juggling needed. The scroll contract is
  // retained: form body has min-h-0 flex-1 overflow-y-auto and the action
  // buttons sit in a footer outside it, so they hold their place on small screens.
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="w-full max-w-md sm:max-w-lg lg:max-w-xl gap-0 p-0 rounded-t-3xl sm:rounded-2xl max-h-[90vh] flex flex-col overflow-hidden"
        data-testid="checkout-modal-card"
      >
        <DialogHeader className="flex flex-row items-center gap-3 border-b border-border px-5 py-4">
          <User size={18} className="text-primary-500" />
          <DialogTitle className="font-semibold text-on">
            {asking
              ? t("approvals.request_title")
              : t("assignments.checkout_modal.title")}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {asking
              ? t("approvals.request_title")
              : t("assignments.checkout_modal.title")}
          </DialogDescription>
        </DialogHeader>

        <div className="px-5 pt-3 pb-1">
          <p className="text-sm text-on-muted">{item.name}</p>
        </div>

        <div className="px-5 pt-4 pb-1">
          <div className="flex rounded-lg border border-border p-0.5 bg-surface-raised">
            <Button
              type="button"
              onClick={() => setMode("person")}
              variant="ghost"
              size="contentSm"
              className={cn(
                "flex-1 py-1.5 min-h-11 md:min-h-0 rounded-md text-sm font-medium",
                mode === "person"
                  ? "bg-surface-card hover:bg-surface-card text-on shadow-sm"
                  : "text-on-muted hover:text-on hover:bg-transparent",
              )}
            >
              <User size={14} />
              {t("assignments.checkout_modal.to_person", "To Person")}
            </Button>
            <Button
              type="button"
              onClick={() => setMode("location")}
              variant="ghost"
              size="contentSm"
              className={cn(
                "flex-1 py-1.5 min-h-11 md:min-h-0 rounded-md text-sm font-medium",
                mode === "location"
                  ? "bg-surface-card hover:bg-surface-card text-on shadow-sm"
                  : "text-on-muted hover:text-on hover:bg-transparent",
              )}
            >
              <MapPin size={14} />
              {t("assignments.checkout_modal.to_location", "To Location")}
            </Button>
          </div>
        </div>

        <form
          id={formId}
          data-testid="checkout-modal-body"
          onSubmit={handleSubmit}
          className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 space-y-4 pt-3"
        >
          {mode === "person" && (
            <>
              <div>
                <EmployeeAutocomplete
                  label={t("assignments.checkout_modal.employee_label")}
                  includeAccounts
                  selected={selectedPerson}
                  onSelect={(person) => {
                    setSelectedPerson(person);
                    setForm((prev) => ({
                      ...prev,
                      assigned_to_name: person.name,
                      assigned_to_email: person.email ?? "",
                    }));
                  }}
                  onClear={() => {
                    setSelectedPerson(null);
                    setForm((prev) => ({
                      ...prev,
                      assigned_to_name: "",
                      assigned_to_email: "",
                    }));
                  }}
                />
                <p className="mt-1 text-xs text-on-muted">
                  {t("assignments.checkout_modal.employee_hint")}
                </p>
              </div>

              <div>
                <Input
                  label={t("assignments.checkout_modal.assigned_to_name")}
                  value={form.assigned_to_name}
                  onChange={(e) => set("assigned_to_name", e.target.value)}
                  placeholder={t(
                    "assignments.checkout_modal.placeholders.name",
                    "e.g. John Smith",
                  )}
                  required
                />
              </div>

              <div>
                <Input
                  label={t("assignments.checkout_modal.assigned_to_email")}
                  type="email"
                  value={form.assigned_to_email}
                  onChange={(e) => set("assigned_to_email", e.target.value)}
                  placeholder={t(
                    "assignments.checkout_modal.placeholders.email",
                    "name@example.com",
                  )}
                  aria-describedby={emailMessageId}
                  aria-invalid={addressUnmatched || undefined}
                />
                <EmailNotice
                  id={emailMessageId}
                  unmatched={addressUnmatched}
                  empty={!form.assigned_to_email.trim()}
                />
              </div>
            </>
          )}

          {mode === "location" && (
            <CheckoutLocationPicker
              value={form.checkout_location_id}
              onChange={(id) => set("checkout_location_id", id)}
              onAdd={() => setShowAddLocation(true)}
            />
          )}

          <div>
            <DateInput
              label={t("assignments.checkout_modal.expected_return")}
              value={form.expected_return_at}
              onChange={setReturnDate}
              min={orgToday}
              error={returnDateError}
            />
            {returnDateError && (
              <p role="alert" className="text-xs text-red-500 mt-1 ml-1">
                {returnDateError}
              </p>
            )}
            {!form.expected_return_at && !returnDateError && (
              <p className="mt-1 ml-1 text-xs text-on-muted">
                {t("assignments.checkout_modal.return_date_consequence")}
              </p>
            )}
          </div>

          <Textarea
            label={t("assignments.checkout_modal.notes")}
            value={form.checkout_notes}
            onChange={(e) => set("checkout_notes", e.target.value)}
            rows={2}
            aria-label={t("assignments.checkout_modal.notes")}
            className="w-full rounded-lg border border-border bg-surface-card text-on px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accent-500 resize-none placeholder:text-on-muted"
          />
        </form>

        <CheckoutFooter
          formId={formId}
          asking={asking}
          pending={pending}
          approvalNeeded={approvalNeeded}
          onRequestApproval={() => send("request")}
          incomplete={
            (mode === "person" && !form.assigned_to_name.trim()) ||
            (mode === "location" && !form.checkout_location_id)
          }
          onClose={onClose}
        />

        {/* QuickAddLocationModal is a separate Radix Dialog; Radix manages
            stacking and focus context between nested dialogs. */}
        <QuickAddLocationModal
          isOpen={showAddLocation}
          onClose={() => setShowAddLocation(false)}
          onCreated={(id: string) => set("checkout_location_id", id)}
        />
      </DialogContent>
    </Dialog>
  );
}
