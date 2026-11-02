import { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { DateInput } from "@/components/ui/DateInput";
import { Textarea } from "@/components/ui/Textarea";
import { Select } from "@/components/ui/Select";
import { InlineQueryError } from "@/components/ui/QueryResult";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/Dialog";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { LocationCombobox } from "@/module-sdk";
import { queryKeys } from "@/hooks/queries/keys";
import { categoriesApi } from "@/lib/api/categories";
import { getCategoryLabel } from "@/modules/equipment/components/assetUtils";
import {
  useCreateCampaign,
  useScopePreview,
} from "@/modules/equipment/hooks/useEquipment";
import type {
  CampaignCreate,
  ScopeType,
} from "@/modules/equipment/api/equipment";
import { useOrganizationTimezone } from "@/hooks/useOrganizationTimezone";
import { instantInsideDay, todayInZone } from "@/utils/zonedDay";

// Campaign creation with a recipient scope picker, on ui/Dialog.
export function CreateCampaignModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("equipment");
  const createMutation = useCreateCampaign();
  // An attestation is a request that travels by mail. The invitations screen
  // reads `can_send_email` and says when there is none; this dialog offers
  // subject lines and reminders, so it owes the reader the same sentence
  // before they configure a campaign that has no way to reach anyone.
  const { data: organization } = useOrganization();
  const canSendEmail = organization?.can_send_email === true;
  // The day travels as an instant inside the organization's day, because the
  // backend reads arrivals through the org clock: a browser-zone arrival
  // stored the next day for every org east of the reader.
  const orgTimezone = useOrganizationTimezone();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [deadline, setDeadline] = useState("");
  const [reminderDays, setReminderDays] = useState("3");
  const [emailSubject, setEmailSubject] = useState("");
  // Campaign scope — ALL / STORAGE / CATEGORY plus the filter id.
  const [scopeType, setScopeType] = useState<ScopeType>("ALL");
  const [scopeFilterId, setScopeFilterId] = useState<string>("");

  // Pull categories so the operator can narrow the scope; the equipment-owned
  // storages (tagged ``equipment``) are searched in their own picker.
  const {
    data: categories = [],
    error: categoriesError,
    refetch: refetchCategories,
  } = useQuery({
    queryKey: queryKeys.categories.equipmentScope,
    queryFn: () => categoriesApi.getAll(),
  });

  const { data: preview } = useScopePreview(
    scopeType,
    scopeFilterId || undefined,
  );

  const scopeHint = useMemo(() => {
    if (scopeType === "STORAGE") return t("attestation.scope.hintStorage");
    if (scopeType === "CATEGORY") return t("attestation.scope.hintCategory");
    return t("attestation.scope.hintAll");
  }, [scopeType, t]);

  const handleSubmit = () => {
    if (!name.trim() || !deadline) return;
    if (scopeType !== "ALL" && !scopeFilterId) return;
    const data: CampaignCreate = {
      name: name.trim(),
      description: description.trim() || undefined,
      deadline: instantInsideDay(deadline, orgTimezone).toISOString(),
      reminder_days_before: Number(reminderDays),
      email_subject: emailSubject.trim() || undefined,
      scope_type: scopeType,
      ...(scopeType !== "ALL" && scopeFilterId
        ? { scope_filter_id: scopeFilterId }
        : {}),
    };
    createMutation.mutate(data, { onSuccess: onClose });
  };

  const filterOptions = useMemo(() => {
    if (scopeType === "CATEGORY") {
      // A built-in category is seeded in English; the picker names it the
      // way the categories screen does.
      return categories.map((c) => ({
        id: String(c.id),
        name: getCategoryLabel(t, { code: c.code, name: c.name }),
      }));
    }
    return [];
  }, [scopeType, categories, t]);

  // ui/Dialog rather than a fixed z-[100] overlay.
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="w-full max-w-md sm:max-w-lg lg:max-w-xl gap-0 p-0 rounded-T-3xl sm:rounded-2xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 space-y-4 pt-3">
          <DialogHeader>
            <DialogTitle>
              {t("attestation.createTitle", "New attestation")}
            </DialogTitle>
            {/* What happens, not how it travels: true with mail and without.
                It used to promise "Send an attestation request" above the
                warning that nothing would be sent; the warning below says
                how the links reach people when there is no mail. */}
            <DialogDescription>
              {t(
                "attestation.createSubtitle",
                "Assignees in scope confirm the assets they hold.",
              )}
            </DialogDescription>
          </DialogHeader>

          {/* Every field is labelled by its own control (§2.10). Half of this
              dialog used to hand-roll `<label>` beside the field in sentence
              case while the other half let the control render its own in
              caps — one form, two label styles, two label-to-field gaps. */}
          <div className="space-y-3">
            <Input
              label={t("attestation.name", "Attestation name")}
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("attestation.namePlaceholder", "Q1 Asset Audit")}
            />

            <Textarea
              label={t("attestation.description", "Description")}
              className="resize-none"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t(
                "attestation.descriptionPlaceholder",
                "Optional details for this audit...",
              )}
            />

            {/* Scope picker. ALL is the default and matches the previous
                behaviour; STORAGE/CATEGORY narrow the recipient list. */}
            <div>
              <Select
                label={t("attestation.scope.label")}
                value={scopeType}
                onChange={(id) => {
                  setScopeType(id as ScopeType);
                  setScopeFilterId("");
                }}
                options={[
                  { id: "ALL", name: t("attestation.scope.all") },
                  { id: "STORAGE", name: t("attestation.scope.storage") },
                  { id: "CATEGORY", name: t("attestation.scope.category") },
                ]}
              />
              <p className="text-xs text-on-muted mt-1.5">{scopeHint}</p>
              {/* How much work the choice actually is. The hint said what a
                  scope means and never how many assets it holds, so a scope
                  covering nobody looked exactly like a scope covering the
                  whole organization until the launch refused. */}
              {preview && (
                <p
                  className={
                    preview.assets === 0
                      ? "text-xs text-amber-700 dark:text-amber-400 mt-1"
                      : "text-xs text-on-muted mt-1"
                  }
                >
                  {preview.assets === 0
                    ? t("attestation.scope.previewEmpty")
                    : t("attestation.scope.previewCount", {
                        assets: preview.assets,
                        people: preview.people,
                      })}
                </p>
              )}
            </div>

            {/* A scope narrowed to a list that never arrived must not offer an
                empty picker: the operator would read "no categories" and
                launch the campaign at everyone instead. The location picker
                says a failed search failed in its own panel. */}
            {scopeType === "CATEGORY" && categoriesError && (
              <InlineQueryError
                error={categoriesError}
                onRetry={() => void refetchCategories()}
              />
            )}
            {scopeType === "STORAGE" && (
              <LocationCombobox
                label={t("attestation.scope.storagePlaceholder")}
                required
                scope={{ contextTag: "equipment" }}
                value={scopeFilterId}
                onChange={setScopeFilterId}
                title={t("attestation.scope.storagePlaceholder")}
              />
            )}
            {scopeType === "CATEGORY" && !categoriesError && (
              <Select
                label={t("attestation.scope.categoryPlaceholder")}
                required
                value={scopeFilterId}
                onChange={setScopeFilterId}
                options={filterOptions}
              />
            )}

            {/* A day, not a timestamp: the reminder scheduler counts whole
                days and the e-mail prints the date alone, so the clock half of
                the old `datetime-local` was never shown to anyone — while a
                picker left at 00:00 quietly expired the token as the deadline
                day began. */}
            {/* The floor is the organization's today: a reader west of the
                org was otherwise offered a day the org has already finished. */}
            <DateInput
              label={t("attestation.deadline", "Deadline")}
              required
              value={deadline}
              onChange={setDeadline}
              min={todayInZone(orgTimezone)}
              presets={["plus1Week", "plus1Month"]}
            />

            <Input
              label={t(
                "attestation.reminderDays",
                "Reminder (days before deadline)",
              )}
              type="number"
              min={0}
              max={30}
              value={reminderDays}
              onChange={(e) => setReminderDays(e.target.value)}
            />

            <Input
              label={t("attestation.emailSubject", "Custom Email Subject")}
              value={emailSubject}
              onChange={(e) => setEmailSubject(e.target.value)}
              placeholder={t(
                "attestation.emailSubjectPlaceholder",
                "Asset attestation required",
              )}
            />

            {!canSendEmail && (
              <p className="text-xs text-on-muted">
                {t("attestation.noEmailWarning")}{" "}
                <Link
                  to="/settings/email"
                  className="underline hover:text-on-secondary"
                >
                  {t("common:settings.organization.inviteNoSmtpLink")}
                </Link>
              </p>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={onClose}>
              {t("common.cancel", "Cancel")}
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={
                !name.trim() ||
                !deadline ||
                (scopeType !== "ALL" && !scopeFilterId) ||
                createMutation.isPending
              }
            >
              {createMutation.isPending
                ? t("common.saving", "Saving...")
                : t("attestation.create", "Create attestation")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
