import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { ImportMapping } from "@/components/import/types";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { queryKeys } from "@/hooks/queries/keys";
import { itemsApi } from "@/lib/api/items";

interface Props {
  file: File;
  mapping: ImportMapping;
  countAsOne: boolean;
}

/** In "add" mode, a sheet whose every row finds stock already here is most
 *  often a second upload: it is said before the quantities are added again. */
export function ImportRepeatWarning({ file, mapping, countAsOne }: Props) {
  const { t } = useTranslation("items");
  const check = useQuery({
    queryKey: queryKeys.items.importCheck(
      `${file.name}:${file.size}:${file.lastModified}`,
      JSON.stringify(mapping),
      countAsOne,
    ),
    queryFn: () => itemsApi.checkImport(file, mapping, countAsOne),
    enabled: Boolean(mapping.name),
    // The stock moves under the sheet: each visit to the step asks anew.
    gcTime: 0,
  });
  if (check.error) {
    return (
      <InlineQueryError
        className="mt-2"
        error={check.error}
        onRetry={() => void check.refetch()}
      />
    );
  }
  const found = check.data;
  if (!found || found.rows === 0 || found.rows_in_stock < found.rows) {
    return null;
  }
  return (
    <p role="alert" className="mt-2 text-sm text-amber-700 dark:text-amber-400">
      {t("import.labelMatch.allInStock", { count: found.rows })}
    </p>
  );
}
