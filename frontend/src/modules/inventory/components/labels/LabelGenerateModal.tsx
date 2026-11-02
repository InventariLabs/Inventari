import { Loader2, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useMemo } from "react";
import type { Dispatch, SetStateAction } from "react";
import { useGenerateLabels } from "@/modules/shared/hooks/useLabels";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { Button } from "@/components/ui/Button";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { Input } from "@/components/ui/Input";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";

/** The purpose id used for plain product labels — the pool's own default. */
const PRODUCT_PURPOSE = "";

interface GenData {
  count: number;
  prefix: string;
  label_type: string;
  description: string;
  target_location_id: string;
  /** Stamped on every label in the batch; read back by the scan page. */
  context_tag: string;
}

interface LabelGenerateModalProps {
  open: boolean;
  onClose: () => void;
  /** Called once the batch exists, before the sheet closes — lets a list
   * that may be filtered to some other state bring the new labels into view. */
  onGenerated?: () => void;
  genData: GenData;
  setGenData: Dispatch<SetStateAction<GenData>>;
  /** Prefix restored when the batch goes back to plain product labels. */
  defaultPrefix: string;
}

export function LabelGenerateModal({
  open,
  onClose,
  onGenerated,
  genData,
  setGenData,
  defaultPrefix,
}: LabelGenerateModalProps) {
  const { t } = useTranslation(["labels", "common"]);
  const generateMutation = useGenerateLabels();
  const enabledModules = useEnabledModulesOptional();

  // A purpose is only worth asking about when something other than plain
  // products can own a label. With no module contributing one, the batch is
  // untagged and the question does not appear.
  const purposes = useMemo(
    () => moduleRegistry.getLabelPurposes(enabledModules),
    [enabledModules],
  );

  if (!open) return null;

  const choosePurpose = (contextTag: string) => {
    const purpose = purposes.find((p) => p.contextTag === contextTag);
    setGenData((prev) => ({
      ...prev,
      context_tag: contextTag,
      // The prefix follows the purpose so a printed sheet is recognisable by
      // eye, but it stays editable — an installation may already print its
      // asset labels under a code of its own.
      prefix: purpose?.defaultPrefix ?? defaultPrefix,
    }));
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      backdropOpacity={60}
      aria-label={t("generateModal.title")}
    >
      <div className="p-4 sm:p-6 border-b flex items-center justify-between bg-primary-50/50 shrink-0">
        <h2 className="text-lg sm:text-xl font-semibold text-on">
          {t("generateModal.title")}
        </h2>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t("common:actions.close")}
        >
          <X size={20} />
        </Button>
      </div>

      <div className="p-4 sm:p-6 space-y-5 overflow-y-auto flex-1">
        <div className="text-center">
          <label
            htmlFor="label-generate-count"
            className="block text-[10px] font-medium text-on-muted uppercase tracking-widest mb-3"
          >
            {t("generateModal.count")}
          </label>
          <div className="max-w-[160px] mx-auto">
            <Input
              id="label-generate-count"
              type="number"
              min="1"
              max="500"
              autoFocus
              value={genData.count}
              onChange={(e) =>
                setGenData({
                  ...genData,
                  count: parseInt(e.target.value) || 1,
                })
              }
              className="text-center text-xl"
            />
          </div>
        </div>

        {purposes.length > 0 && (
          <ChoiceGroup
            label={t("generateModal.purpose")}
            hint={t("generateModal.purposeHelp")}
            value={genData.context_tag}
            onChange={choosePurpose}
            options={[
              {
                id: PRODUCT_PURPOSE,
                label: t("generateModal.purposeProduct"),
              },
              ...purposes.map((purpose) => ({
                id: purpose.contextTag,
                label: t(purpose.labelKey, purpose.contextTag),
              })),
            ]}
          />
        )}

        <div>
          <Input
            label={t("generateModal.prefix")}
            type="text"
            maxLength={5}
            value={genData.prefix}
            onChange={(e) =>
              setGenData({
                ...genData,
                prefix: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""),
              })
            }
            placeholder={t("generateModal.prefixPlaceholder")}
            className="font-mono"
          />
          <p className="text-[10px] text-on-muted mt-1 ml-1">
            {t("generateModal.prefixHelp")}
          </p>
        </div>

        <div>
          <Input
            label={t("generateModal.description")}
            type="text"
            value={genData.description}
            onChange={(e) =>
              setGenData({ ...genData, description: e.target.value })
            }
            placeholder={t("generateModal.descriptionPlaceholder")}
          />
        </div>
      </div>

      <SheetFooter>
        <SheetActions className="gap-3">
          <Button variant="outline" onClick={onClose}>
            {t("common:actions.cancel")}
          </Button>
          <Button
            data-testid="export-labels-btn"
            onClick={() =>
              generateMutation.mutate(genData, {
                onSuccess: (data) => {
                  toast.success(t("generatedSuccess", { count: data.length }));
                  onGenerated?.();
                  onClose();
                },
              })
            }
            // The field settles every other shape while the reader types —
            // it strips anything outside [A-Z0-9] and caps the length, so
            // what it holds always scans. An emptied field was the one
            // exception, and it left as a request that came back a 422
            // with no field attached to it.
            disabled={
              generateMutation.isPending || genData.prefix.trim() === ""
            }
          >
            {generateMutation.isPending ? (
              <Loader2 size={20} className="animate-spin" />
            ) : (
              t("actions.generateNow")
            )}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
