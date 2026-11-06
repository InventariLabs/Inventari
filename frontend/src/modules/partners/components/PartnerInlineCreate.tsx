import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { extractApiError } from "@/lib/errors";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useCreatePartner } from "@/modules/partners/hooks/usePartners";
import type { Partner, PartnerType } from "@/types";

const QUICK_TYPES: PartnerType[] = ["SUPPLIER", "CUSTOMER", "BOTH"];

interface PartnerInlineCreateProps {
  initialName: string;
  /**
   * The roles the calling field accepts; the layer starts on the first one
   * and offers no other. A partner of a foreign role is exactly how a
   * required field ended up "filled" with a partner its own picker could
   * not show. Absent, the generic quick set is offered.
   */
  roleTypes?: readonly PartnerType[];
  onCreated: (partner: Partner) => void;
  onCancel: () => void;
  /**
   * Id of the field that opened the layer. The layer unmounts while its
   * Cancel or Add button holds the focus, which then falls to the page body —
   * behind a dialog the next Tab would leave. The field gets it back.
   */
  returnFocusId?: string;
}

export function PartnerInlineCreate({
  initialName,
  roleTypes,
  onCreated,
  onCancel,
  returnFocusId,
}: PartnerInlineCreateProps) {
  const { t } = useTranslation(["partners", "common"]);
  const createMutation = useCreatePartner();
  const offeredTypes = roleTypes ?? QUICK_TYPES;
  const [name, setName] = useState(initialName);
  const [type, setType] = useState<PartnerType>(offeredTypes[0] ?? "SUPPLIER");
  // Asked here because a country that requires a partner's tax ID refuses
  // to confirm the document this layer was opened from without one — unless
  // the partner is a private person, who has none.
  const [taxId, setTaxId] = useState("");
  const [isConsumer, setIsConsumer] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const layerRef = useRef<HTMLDivElement>(null);

  // The layer opens under the field that asked for it, which on a short
  // window is below the fold: the click read as dead. Bring the whole box
  // into view, then focus the name without a second scroll.
  useEffect(() => {
    layerRef.current?.scrollIntoView?.({ block: "nearest" });
    nameRef.current?.focus({ preventScroll: true });
    nameRef.current?.select();
  }, []);

  // Two frames on, once the layer is gone: if nobody took the focus it is on
  // the body, and the field that asked for the layer is where it belongs.
  useEffect(() => {
    if (!returnFocusId) return;
    return () => {
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          const active = document.activeElement;
          if (!active || active === document.body) {
            document.getElementById(returnFocusId)?.focus();
          }
        }),
      );
    };
  }, [returnFocusId]);

  const handleCreate = () => {
    const trimmed = name.trim();
    if (!trimmed) {
      toast.error(t("common:validation.nameRequired"));
      return;
    }

    createMutation.mutate(
      {
        name: trimmed,
        type,
        tax_id: taxId.trim() || null,
        is_consumer: isConsumer,
      },
      {
        onSuccess: (partner) => {
          toast.success(t("inlineCreateSuccess", { name: partner.name }));
          onCreated(partner);
        },
        onError: (err: unknown) => {
          toast.error(extractApiError(err, t("errors.createFailed")));
        },
      },
    );
  };

  const handleNameKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleCreate();
    }
  };

  return (
    <div
      ref={layerRef}
      className="rounded-xl border border-primary-200 bg-primary-50/40 p-3 space-y-3"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-on">
            {t("form.createTitle")}
          </h3>
          <p className="text-xs text-on-secondary mt-0.5">
            {t("inlineCreateHint")}
          </p>
        </div>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          {t("common:form.cancel")}
        </Button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 items-end gap-3">
        <Input
          ref={nameRef}
          label={t("fields.name")}
          aria-required="true"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={handleNameKeyDown}
          placeholder={t("form.namePlaceholder")}
        />
        <NativeSelect
          label={t("fields.type")}
          value={type}
          onChange={(e) => setType(e.target.value as PartnerType)}
        >
          {offeredTypes.map((pt) => (
            <option key={pt} value={pt}>
              {t(`types.${pt}`)}
            </option>
          ))}
        </NativeSelect>
        <Input
          label={t("fields.taxId")}
          value={taxId}
          onChange={(e) => setTaxId(e.target.value)}
          onKeyDown={handleNameKeyDown}
          placeholder={t("form.taxIdPlaceholder")}
        />
        <div className="flex items-center sm:h-10">
          <Checkbox
            id="partner-inline-create-consumer"
            label={t("fields.isConsumer")}
            checked={isConsumer}
            onChange={(e) => setIsConsumer(e.target.checked)}
          />
        </div>
      </div>

      <div className="flex justify-end">
        <Button
          type="button"
          data-testid="partner-inline-create-submit"
          onClick={handleCreate}
          disabled={createMutation.isPending || !name.trim()}
        >
          {createMutation.isPending
            ? t("form.saving")
            : t("actions.addPartner")}
        </Button>
      </div>
    </div>
  );
}
