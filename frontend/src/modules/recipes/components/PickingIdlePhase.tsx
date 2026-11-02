import { Button } from "@/components/ui/Button";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/Sheet";
import ServingsSelector from "./ServingsSelector";

interface Props {
  recipeName: string;
  servings: number;
  onServingsChange: (v: number) => void;
  cleanServingsHint: string | null;
  isLoading: boolean;
  error: string | null;
  onStart: () => void;
  onClose: () => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}

export default function PickingIdlePhase({
  recipeName,
  servings,
  onServingsChange,
  cleanServingsHint,
  isLoading,
  error,
  onStart,
  onClose,
  t,
}: Props) {
  return (
    <Sheet
      open
      onClose={onClose}
      zIndex="modal"
      maxWidth="sm"
      aria-label={recipeName}
    >
      <SheetHeader
        onClose={onClose}
        closeLabel={t("common:a11y.close")}
        className="px-5 py-3.5"
      >
        <SheetTitle className="text-base truncate">{recipeName}</SheetTitle>
      </SheetHeader>
      <SheetBody className="px-5 py-5 space-y-4">
        <p className="text-sm text-on-secondary">
          {t("picking.start_hint", { ns: "recipes" })}
        </p>
        <ServingsSelector
          value={servings}
          onChange={onServingsChange}
          label={t("picking.servings_selector", { ns: "recipes" })}
          cleanHint={cleanServingsHint}
        />
        {error && (
          <p className="text-sm text-on-danger font-medium bg-red-50 rounded-lg p-3">
            {error}
          </p>
        )}
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onClose}>
            {t("common:form.cancel")}
          </Button>
          <Button onClick={onStart} isLoading={isLoading} className="gap-2">
            {t("picking.start", { ns: "recipes" })}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
