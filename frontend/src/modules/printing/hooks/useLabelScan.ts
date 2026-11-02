import { useQuery } from "@tanstack/react-query";
import { labelsApi } from "@/lib/api/labels";
import { queryKeys } from "@/hooks/queries/keys";
import type { LabelScanView } from "@/types";

export function useLabelScan(code: string) {
  return useQuery<LabelScanView>({
    queryKey: queryKeys.printing.labelScan(code),
    queryFn: () => labelsApi.scan(code),
    enabled: !!code,
    retry: false,
  });
}
