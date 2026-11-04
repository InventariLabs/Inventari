import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { modulesApi } from "@/lib/api/modules";
import { queryKeys } from "@/hooks/queries/keys";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

export function useModuleSettings(moduleName: string | undefined) {
  return useQuery({
    queryKey: moduleName
      ? queryKeys.modules.settings(moduleName)
      : queryKeys.modules.settingsNone,
    queryFn: () => modulesApi.getSettings(moduleName as string),
    enabled: Boolean(moduleName),
  });
}

/** `quiet` leaves the confirmation to a page that saves several things at once. */
export function useUpdateModuleSettings(
  moduleName: string,
  options?: { quiet?: boolean },
) {
  const { t } = useTranslation("common");
  return useAppMutation(
    (settings: Record<string, unknown>) =>
      modulesApi.updateSettings(moduleName, settings),
    (qc) => {
      qc.invalidateQueries({
        queryKey: queryKeys.modules.settings(moduleName),
      });
      if (!options?.quiet) toast.success(t("settings.moduleSettings.saved"));
    },
  );
}
