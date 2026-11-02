import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { Save, ShieldCheck } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { QueryError } from "@/components/ui/QueryResult";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { extractApiError, extractFieldValidationError } from "@/lib/errors";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import { usePOSettings, useUpdatePOSettings } from "../hooks/usePurchaseOrders";
import { POApprovalWorkflowWarning } from "./POApprovalWorkflowWarning";

/**
 * Per-org PO approval settings.
 *
 * Backed by ``GET/PUT /purchase-orders/settings`` (POSettings): either
 * every PO confirmation requires approval, or only POs whose net total
 * exceeds the threshold do.
 */
export function POApprovalSettings() {
  const { t } = useTranslation("purchase_orders");
  const { data: settings, isLoading, isError, refetch } = usePOSettings();
  const updateSettings = useUpdatePOSettings();
  const orgCurrency = useOrganizationCurrency();
  // The PUT behind this form answers to purchase_orders:manage: whether an
  // order needs approval is not a buyer's own call. The form says so up
  // front, in the words the other module settings screens use, instead of
  // letting the save fail. A viewer is told the broader thing it lacks, as
  // the Production settings tell theirs (MakerSettingsPanel).
  const canManage = useCanManage("purchase_orders");
  const canWrite = useCanWrite("purchase_orders");

  const [threshold, setThreshold] = useState<string>("");
  const [requireAll, setRequireAll] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [thresholdError, setThresholdError] = useState<string | null>(null);

  // Hydrate local state once from the server values.
  if (!initialized && settings) {
    setThreshold(
      settings.approval_threshold != null
        ? String(settings.approval_threshold)
        : "",
    );
    setRequireAll(settings.approval_required);
    setInitialized(true);
  }

  if (!canManage) {
    return (
      <ReadOnlyNotice
        module="purchase_orders"
        right={canWrite ? "manage" : "write"}
      />
    );
  }

  const failOnThreshold = (message: string) => {
    setThresholdError(message);
    document.getElementById("po-approval-threshold")?.focus();
  };

  const handleSave = async () => {
    // The `min="0"` attribute was decorative: there is no native form
    // validation here, so a negative threshold went to the server and came
    // back as a raw Pydantic sentence with no field attached to it.
    const parsed = threshold.trim() === "" ? null : Number(threshold);
    if (parsed != null && parsed < 0) {
      failOnThreshold(t("settings.thresholdNegative"));
      return;
    }
    setThresholdError(null);

    try {
      await updateSettings.mutateAsync({
        approval_threshold: parsed,
        approval_required: requireAll,
      });
      toast.success(t("settings.saved"));
    } catch (err) {
      // A 422 the guards above did not anticipate still belongs on the
      // field, not in a toast that leaves the reader hunting for what the
      // server objected to.
      const fieldMessage = extractFieldValidationError(
        err,
        "approval_threshold",
      );
      if (fieldMessage) {
        failOnThreshold(fieldMessage);
        return;
      }
      toast.error(extractApiError(err, t("unknownError")));
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-5 text-sm text-on-secondary">
          {t("common:messages.loading")}
        </CardContent>
      </Card>
    );
  }

  // The defaults this form falls back to are not neutral: an unticked box and
  // an empty field are a live instruction to stop requiring approval, and
  // saving them sent exactly that. A form nobody filled from the server has
  // no business offering to write to it.
  if (isError) {
    return (
      <Card>
        <CardContent className="p-5">
          <QueryError
            message={t("settings.loadFailed")}
            onRetry={() => void refetch()}
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="p-5">
        <div className="mb-4 flex items-center gap-2">
          <ShieldCheck size={18} className="text-on-muted" />
          <h2 className="text-sm font-medium text-on">{t("settings.title")}</h2>
        </div>
        <p className="mb-4 text-sm text-on-secondary">
          {t("settings.description")}
        </p>

        <div className="space-y-4">
          <POApprovalWorkflowWarning
            approvalRequested={requireAll || threshold.trim() !== ""}
          />

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={requireAll}
              onChange={(e) => setRequireAll(e.target.checked)}
              className="h-4 w-4 rounded border-on-muted"
            />
            {t("settings.requireAll")}
          </label>

          <div className="flex flex-col gap-1">
            <label
              htmlFor="po-approval-threshold"
              className="block text-sm text-on-secondary"
            >
              {orgCurrency
                ? t("settings.thresholdLabelWithCurrency", {
                    currency: orgCurrency,
                  })
                : t("settings.thresholdLabel")}
            </label>
            <Input
              wrapperClassName="max-w-xs"
              id="po-approval-threshold"
              type="number"
              min="0"
              step="0.01"
              value={threshold}
              error={thresholdError ?? undefined}
              onChange={(e) => {
                setThreshold(e.target.value);
                if (thresholdError) setThresholdError(null);
              }}
              placeholder={t("settings.thresholdPlaceholder")}
            />
            <p className="text-xs text-on-muted">
              {t("settings.thresholdHint")}
            </p>
          </div>

          <Button
            variant="primary"
            size="sm"
            leftIcon={<Save size={16} />}
            onClick={handleSave}
            isLoading={updateSettings.isPending}
          >
            {t("settings.save")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
