import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle, EyeOff, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { extractApiError } from "@/lib/errors";
import { useNavigate } from "react-router-dom";
import { useCreateStockTake } from "@/modules/stock_takes/hooks/useStockTakes";
import { useLocationOffer } from "@/module-sdk";
import { LocationCombobox } from "@/module-sdk";
import { StorageRequired } from "@/modules/shared/components/StorageRequired";
import { QueryError } from "@/components/ui/QueryResult";
import type { StockTakeCreate } from "@/modules/stock_takes/types/stock-takes";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Checkbox } from "@/components/ui/Checkbox";
import { Sheet } from "@/components/ui/Sheet";

interface StockTakeCreateModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** The location the form opens with, when the reader came from one. */
  initialStorageId?: string;
}

export default function StockTakeCreateModal({
  isOpen,
  onClose,
  initialStorageId,
}: StockTakeCreateModalProps) {
  const { t } = useTranslation("stock_takes");
  const [formData, setFormData] = useState<StockTakeCreate>({
    location_id: initialStorageId ?? "",
    name: "",
    blind_mode: false,
    tolerance_percent: undefined,
    require_full_count: true,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const navigate = useNavigate();
  // A stock take counts what stock flows count: a place a module owns is not
  // where warehouse stock stands, so those stay out of the picker whatever
  // the module-data policy mixes into the general lists — counting a module's
  // location is the module's job. No keepId — a new stock take holds no
  // location yet.
  const {
    total: storageCount,
    first: storages,
    isError: isStoragesError,
    refetch: refetchStorages,
  } = useLocationOffer({ purpose: "stock" });
  const createMutation = useCreateStockTake();

  // Asking for a decision that has one sensible answer is pure cost: where
  // the picker may offer exactly one location, that is the answer already.
  // It fills an empty selection only — where the reader came from a location,
  // that one stands.
  useEffect(() => {
    if (!isOpen || formData.location_id) return;
    if (storageCount !== 1) return;
    setFormData((prev) => ({ ...prev, location_id: storages[0].id }));
  }, [isOpen, formData.location_id, storageCount, storages]);

  const validateForm = () => {
    const newErrors: Record<string, string> = {};
    if (!formData.location_id)
      newErrors.location_id = t("validation.storageRequired");
    if (!formData.name.trim())
      newErrors.name = t("common:validation.nameRequired");
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (validateForm()) {
      createMutation.mutate(formData, {
        onSuccess: (newStockTake) => {
          onClose();
          setFormData({
            location_id: "",
            name: "",
            blind_mode: false,
            tolerance_percent: undefined,
            require_full_count: true,
          });
          navigate(`/inventory/stock-takes/${newStockTake.id}/counting`);
        },
        onError: (error: unknown) => {
          setErrors({
            submit: extractApiError(error, t("errors.createFailed")),
          });
        },
      });
    }
  };

  if (!isOpen) return null;

  return (
    <Sheet
      open={isOpen}
      onClose={onClose}
      maxWidth="xl"
      aria-label={t("modal.title")}
    >
      <div className="flex items-center justify-between p-4 border-b border-border">
        <h2 className="text-lg font-semibold text-on">{t("modal.title")}</h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:actions.close")}
        >
          <X size={20} />
        </Button>
      </div>

      <div className="overflow-y-auto p-4 flex-1">
        <form
          id="stock-take-create-form"
          onSubmit={handleSubmit}
          className="space-y-4"
        >
          {errors.submit && (
            <div className="flex items-center gap-2 p-3 bg-red-50 text-on-danger dark:bg-red-500/10 rounded-lg">
              <AlertCircle size={20} />
              <span>{errors.submit}</span>
            </div>
          )}

          {isStoragesError ? (
            // The read never arrived. "You have no storages" is the answer
            // to an empty list; a failed one says so and offers to ask again
            // — the guard below cannot cover it: `storages` is undefined on
            // a failure, so that path never opened either.
            <QueryError onRetry={() => refetchStorages()} />
          ) : storageCount === 0 ? (
            // A required select holding zero options states the requirement
            // and gives no way to meet it without abandoning the modal. The
            // advice under it follows the picker's own purpose: a stock flow
            // keeps module places out on purpose, so a settings switch is not
            // the way back into this list.
            <StorageRequired purpose="stock" />
          ) : (
            <div>
              {/* The star comes from the control, not from the string: baked
                  into the label it reaches a screen reader as "star". */}
              {/* A stock take covers the location and all its descendants,
                  so every location is countable. ADR-018 makes that the rule
                  everywhere: leafness never decided what may hold things. */}
              <LocationCombobox
                label={t("modal.storageLabel")}
                required
                scope={{ purpose: "stock" }}
                value={formData.location_id}
                onChange={(id) => setFormData({ ...formData, location_id: id })}
                placeholder={t("modal.storagePlaceholder")}
                title={t("modal.storageLabel")}
                error={errors.location_id}
              />
            </div>
          )}

          <div>
            <Input
              label={t("modal.nameLabel")}
              required
              type="text"
              value={formData.name}
              onChange={(e) =>
                setFormData({ ...formData, name: e.target.value })
              }
              placeholder={t("modal.namePlaceholder")}
              error={errors.name}
            />
          </div>

          <div className="flex items-center gap-3 pt-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <EyeOff size={18} className="text-on-muted" />
              <span className="text-sm text-on-secondary">
                {t("modal.blindMode")}
              </span>
              <Checkbox
                checked={formData.blind_mode || false}
                onChange={(e) =>
                  setFormData({ ...formData, blind_mode: e.target.checked })
                }
              />
            </label>
          </div>
          <div className="flex items-center gap-3 pt-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <CheckCircle size={18} className="text-on-muted" />
              <span className="text-sm text-on-secondary">
                {t("modal.requireFullCount")}
              </span>
              <Checkbox
                checked={formData.require_full_count ?? true}
                onChange={(e) =>
                  setFormData({
                    ...formData,
                    require_full_count: e.target.checked,
                  })
                }
              />
            </label>
          </div>
          <div>
            <Input
              label={t("modal.toleranceLabel")}
              type="number"
              value={formData.tolerance_percent ?? ""}
              onChange={(e) =>
                setFormData({
                  ...formData,
                  tolerance_percent: e.target.value
                    ? Number(e.target.value)
                    : undefined,
                })
              }
              min="0"
              max="100"
              step="0.1"
              placeholder={t("modal.tolerancePlaceholder")}
            />
          </div>
        </form>
      </div>

      {/* actions live outside the scroll area so they are always
          reachable — at 1280×577 they used to sit below the fold inside
          the scrolling form and clicks never fired. */}
      <div className="flex items-center justify-end gap-2 p-4 border-t border-border shrink-0">
        <Button variant="outline" onClick={onClose}>
          {t("modal.cancel")}
        </Button>
        <Button
          type="submit"
          form="stock-take-create-form"
          disabled={createMutation.isPending}
        >
          {createMutation.isPending ? t("modal.creating") : t("modal.create")}
        </Button>
      </div>
    </Sheet>
  );
}
