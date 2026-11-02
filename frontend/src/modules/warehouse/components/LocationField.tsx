import { useTranslation } from "react-i18next";
import { storageModuleBadge } from "@/utils/storageModuleBadge";
import {
  SearchableCombobox,
  type SearchableComboboxProps,
} from "@/components/ui/SearchableCombobox";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useLocationPicker } from "@/module-sdk";
import type { LocationScope } from "@/module-sdk";

/**
 * A location field: the places a scope offers, searched on the server as the
 * reader types. A stock flow's scope is the default — the places that may
 * hold goods. `except` leaves places out of the offer (a move cannot end
 * where it starts; a list of targets does not offer a target twice).
 *
 * A search that failed says so, with a way to try again: an empty list would
 * read as "this organization has no places".
 */
export function LocationField({
  except,
  scope = { purpose: "stock" },
  value,
  ...rest
}: Omit<SearchableComboboxProps, "options" | "loading" | "onSearchChange"> & {
  except?: ReadonlyArray<string | null | undefined>;
  scope?: LocationScope;
}) {
  const { t } = useTranslation();
  const picker = useLocationPicker(scope, value);
  // A place a module owns says whose it is.
  const options = picker.options
    .filter((option) => !except?.includes(option.id))
    .map(({ contextTag, ...option }) => ({
      ...option,
      badge: storageModuleBadge(t, contextTag),
    }));
  return (
    <>
      <SearchableCombobox
        {...rest}
        value={value}
        options={options}
        loading={picker.loading}
        onSearchChange={picker.setSearch}
      />
      {picker.error && (
        <InlineQueryError
          error={picker.error}
          onRetry={picker.retry}
          className="sm:col-span-2"
        />
      )}
    </>
  );
}
