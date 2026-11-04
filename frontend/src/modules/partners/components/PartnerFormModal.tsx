import { useState } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import { extractApiError } from "@/lib/errors";
import {
  useCreatePartner,
  useUpdatePartner,
} from "@/modules/partners/hooks/usePartners";
import { PartnerAddressSection } from "@/modules/partners/components/PartnerAddressSection";
import { PARTNER_TYPES } from "@/modules/partners/partnerRoles";
import type { Partner, PartnerAddress, PartnerCreate } from "@/types";

// Deliberately loose: these guard against a typo, not against every address
// the RFCs allow. Anything stricter starts rejecting valid addresses.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const WEBSITE_PATTERN = /^(https?:\/\/)?[^\s.]+\.[^\s]{2,}$/i;
const NAME_FIELD_ID = "partner-form-name";
const EMAIL_FIELD_ID = "partner-form-email";
const WEBSITE_FIELD_ID = "partner-form-website";
const FIELD_IDS = {
  name: NAME_FIELD_ID,
  email: EMAIL_FIELD_ID,
  website: WEBSITE_FIELD_ID,
};

interface Props {
  partner?: Partner;
  onClose: () => void;
}

// The form starts from the partner being edited, or empty for a new one.
function toForm(partner?: Partner): PartnerCreate {
  return {
    name: partner?.name ?? "",
    code: partner?.code ?? "",
    type: partner?.type ?? "SUPPLIER",
    tax_id: partner?.tax_id ?? "",
    is_consumer: partner?.is_consumer === true,
    email: partner?.email ?? "",
    phone: partner?.phone ?? "",
    website: partner?.website ?? "",
    contact_person: partner?.contact_person ?? "",
    address: partner?.address ?? null,
    notes: partner?.notes ?? "",
  };
}

export default function PartnerFormModal({ partner, onClose }: Props) {
  const { t } = useTranslation(["partners", "common"]);
  const isEdit = !!partner;

  const [fieldErrors, setFieldErrors] = useState<{
    name?: string;
    email?: string;
    website?: string;
  }>({});
  const [form, setForm] = useState<PartnerCreate>(() => toForm(partner));

  // Expanded by default: a supplier being created must see that an
  // address exists, rather than having to guess at a collapsed section.
  const [showAddress, setShowAddress] = useState(true);

  const isEmployee = form.type === "EMPLOYEE";

  const setAddress = (field: keyof PartnerAddress, value: string) =>
    setForm((prev) => ({
      ...prev,
      address: { ...(prev.address ?? {}), [field]: value || undefined },
    }));

  const createMutation = useCreatePartner();
  const updateMutation = useUpdatePartner();
  const isLoading = createMutation.isPending || updateMutation.isPending;

  const set = (field: keyof PartnerCreate, value: string) => {
    // Name is the one field that is never null: it is trimmed on submit.
    setForm((prev) => ({
      ...prev,
      [field]: field === "name" ? value : value || null,
    }));
    // Editing a field clears the message it carries, if it carries one.
    setFieldErrors((prev) =>
      prev[field as keyof typeof prev] ? { ...prev, [field]: undefined } : prev,
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    // The browser's own validation speaks the operating system's language and
    // cannot be translated or styled, so an app shipping five languages must
    // not delegate to it (the form carries noValidate for the same reason).
    // Each refusal sits on its field, and the first of them takes the focus;
    // a toast alone names nothing on the form and is gone before it is read.
    const email = form.email?.trim() ?? "";
    const website = form.website?.trim() ?? "";
    const nextErrors: { name?: string; email?: string; website?: string } = {};
    if (!form.name.trim()) {
      nextErrors.name = t("common:validation.nameRequired");
    }
    if (email && !EMAIL_PATTERN.test(email)) {
      nextErrors.email = t("errors.invalidEmail");
    }
    if (website && !WEBSITE_PATTERN.test(website)) {
      nextErrors.website = t("errors.invalidWebsite");
    }
    setFieldErrors(nextErrors);
    const [firstInvalid] = Object.keys(
      nextErrors,
    ) as (keyof typeof nextErrors)[];
    if (firstInvalid) {
      document.getElementById(FIELD_IDS[firstInvalid])?.focus();
      return;
    }

    const payload: PartnerCreate = {
      ...form,
      // Normalise empty strings to null for optional fields
      code: form.code?.trim() || null,
      tax_id: form.tax_id?.trim() || null,
      email: form.email?.trim() || null,
      phone: form.phone?.trim() || null,
      website: form.website?.trim() || null,
      contact_person: form.contact_person?.trim() || null,
      notes: form.notes?.trim() || null,
      // Keep address only if at least one field is filled
      address:
        form.address && Object.values(form.address).some((v) => v?.trim())
          ? form.address
          : null,
    };

    if (isEdit) {
      updateMutation.mutate(
        { id: partner.id, data: payload },
        {
          onSuccess: () => {
            toast.success(t("toasts.saved"));
            onClose();
          },
          onError: (err) =>
            toast.error(extractApiError(err, t("errors.saveFailed"))),
        },
      );
    } else {
      createMutation.mutate(payload, {
        onSuccess: () => {
          toast.success(t("toasts.created"));
          onClose();
        },
        onError: (err) =>
          toast.error(extractApiError(err, t("errors.createFailed"))),
      });
    }
  };

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="xl"
      aria-label={isEdit ? t("form.editTitle") : t("form.createTitle")}
    >
      {/* Header */}
      <div className="flex items-center justify-between p-5 border-b border-border flex-shrink-0">
        <h2 className="font-semibold text-on">
          {isEdit ? t("form.editTitle") : t("form.createTitle")}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:actions.close")}
        >
          <X size={18} />
        </Button>
      </div>

      {/* Form */}
      <form
        noValidate
        onSubmit={handleSubmit}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div className="flex-1 min-h-0 space-y-4 overflow-y-auto p-5">
          {/* Name + Type */}
          <div className="grid grid-cols-1 items-end sm:grid-cols-2 gap-3">
            <div>
              <Input
                id={NAME_FIELD_ID}
                label={isEmployee ? t("fields.fullName") : t("fields.name")}
                error={fieldErrors.name}
                required
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder={
                  isEmployee
                    ? t("form.fullNamePlaceholder")
                    : t("form.namePlaceholder")
                }
              />
            </div>
            <div className="space-y-1.5">
              <NativeSelect
                // The star used to be baked into the label string, where a
                // screen reader read it as the word "star"; the component draws
                // it from `required` and announces the requirement instead.
                label={t("fields.type")}
                required
                value={form.type}
                onChange={(e) => set("type", e.target.value)}
              >
                {PARTNER_TYPES.map((pt) => (
                  <option key={pt} value={pt}>
                    {t(`types.${pt}`)}
                  </option>
                ))}
              </NativeSelect>
            </div>
          </div>

          {/* Tax ID and private person — hidden for employees */}
          {!isEmployee && (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 items-end gap-3">
                <div>
                  <Input
                    label={t("fields.taxId")}
                    value={form.tax_id ?? ""}
                    onChange={(e) => set("tax_id", e.target.value)}
                    placeholder={t("form.taxIdPlaceholder")}
                  />
                </div>
                <div>
                  <Input
                    label={t("fields.code")}
                    value={form.code ?? ""}
                    onChange={(e) => set("code", e.target.value)}
                    placeholder={t("form.codePlaceholder")}
                  />
                </div>
              </div>
              <div>
                <Checkbox
                  id="partner-form-consumer"
                  label={t("fields.isConsumer")}
                  aria-describedby="partner-form-consumer-hint"
                  checked={form.is_consumer}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      is_consumer: e.target.checked,
                    }))
                  }
                />
                <p
                  id="partner-form-consumer-hint"
                  className="text-xs text-on-muted mt-1 ml-6"
                >
                  {t("form.isConsumerHint")}
                </p>
              </div>
            </>
          )}

          {/* Email + Phone */}
          <div className="grid grid-cols-1 sm:grid-cols-2 items-end gap-3">
            <div>
              <Input
                id={EMAIL_FIELD_ID}
                type="email"
                label={t("fields.email")}
                error={fieldErrors.email}
                value={form.email ?? ""}
                onChange={(e) => set("email", e.target.value)}
                placeholder={t("form.emailPlaceholder")}
              />
            </div>
            <div>
              <Input
                label={t("fields.phone")}
                value={form.phone ?? ""}
                onChange={(e) => set("phone", e.target.value)}
                placeholder={t("form.phonePlaceholder")}
              />
            </div>
          </div>

          {/* Website — hidden for employees */}
          {!isEmployee && (
            <div>
              <Input
                id={WEBSITE_FIELD_ID}
                type="url"
                label={t("fields.website")}
                error={fieldErrors.website}
                value={form.website ?? ""}
                onChange={(e) => set("website", e.target.value)}
                placeholder={t("form.websitePlaceholder")}
              />
            </div>
          )}
          <div>
            <Input
              label={
                isEmployee ? t("fields.position") : t("fields.contactPerson")
              }
              value={form.contact_person ?? ""}
              onChange={(e) => set("contact_person", e.target.value)}
              placeholder={
                isEmployee
                  ? t("form.positionPlaceholder")
                  : t("form.contactPersonPlaceholder")
              }
            />
          </div>

          {/* Notes */}
          <Textarea
            label={t("fields.notes")}
            value={form.notes ?? ""}
            onChange={(e) => set("notes", e.target.value)}
            placeholder={t("form.notesPlaceholder")}
            rows={3}
            className="w-full px-3 py-2 text-sm border border-border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 bg-surface-card text-on placeholder:text-on-muted resize-none transition-all duration-200"
          />

          {/* Address — collapsible */}
          {!isEmployee && (
            <PartnerAddressSection
              address={form.address}
              open={showAddress}
              onToggle={() => setShowAddress((v) => !v)}
              onChange={setAddress}
            />
          )}
        </div>

        {/* Actions: outside the scrolling body, so a phone never has to
            swipe past the last field to find Save. */}
        <SheetFooter>
          <SheetActions>
            <Button type="button" variant="outline" onClick={onClose}>
              {t("common:form.cancel")}
            </Button>
            <Button type="submit" isLoading={isLoading}>
              {isLoading ? t("form.saving") : t("common:form.save")}
            </Button>
          </SheetActions>
        </SheetFooter>
      </form>
    </Sheet>
  );
}
