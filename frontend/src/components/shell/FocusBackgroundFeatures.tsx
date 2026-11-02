import { Suspense, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useModules } from "@/contexts/ModulesContext";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { makeTDynamic } from "@/lib/i18nHelpers";

export function FocusBackgroundFeatures({
  moduleName,
}: {
  moduleName: string;
}) {
  const { t } = useTranslation();
  const translate = makeTDynamic(t);
  const { enabledModules } = useModules();
  const features = moduleRegistry.getBackgroundFeatures(
    moduleName,
    enabledModules,
  );
  const [open, setOpen] = useState<string | null>(null);
  const active = features.find(
    (feature) => `${feature.provider}:${feature.feature}` === open,
  );
  const Panel = active?.component;
  return (
    <div className="flex items-center gap-1">
      {features.map((feature) => {
        const key = `${feature.provider}:${feature.feature}`;
        return (
          <Button
            key={key}
            variant="ghost"
            size="sm"
            onClick={() => setOpen(key)}
          >
            {translate(feature.labelKey)}
          </Button>
        );
      })}
      <Sheet
        open={Boolean(active)}
        onClose={() => setOpen(null)}
        maxWidth="3xl"
        aria-label={active ? translate(active.labelKey) : undefined}
      >
        {active && Panel && (
          <>
            <SheetHeader
              title={translate(active.labelKey)}
              onClose={() => setOpen(null)}
            />
            <SheetBody className="p-5">
              <Suspense fallback={<LoadingSpinner />}>
                <Panel />
              </Suspense>
            </SheetBody>
          </>
        )}
      </Sheet>
    </div>
  );
}
