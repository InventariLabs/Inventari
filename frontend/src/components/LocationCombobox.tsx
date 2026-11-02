import { useTranslation } from "react-i18next";
import { storageModuleBadge } from "@/utils/storageModuleBadge";
import {
  SearchableCombobox,
  type SearchableComboboxProps,
} from "@/components/ui/SearchableCombobox";
import { LocationSearchFailed } from "@/components/LocationSearchFailed";
import { useLocationPicker } from "@/hooks/useLocationPicker";
import type { LocationScope } from "@/hooks/queries/useLocations";

type LocationComboboxProps = Omit<
  SearchableComboboxProps,
  "options" | "loading" | "onSearchChange"
> & {
  /** What the field may offer; see `LocationScope`. */
  scope?: LocationScope;
};

/**
 * A field that picks a location by searching for it.
 *
 * Every location picker is this one: the list is a page the server answers
 * for what was typed, so it costs the same with ten places as with ten
 * thousand, and the screen around it never holds the organization's
 * locations. `value` is named even when it is not on the page.
 */
export function LocationCombobox({
  scope = {},
  value,
  ...rest
}: LocationComboboxProps) {
  const { t } = useTranslation();
  const picker = useLocationPicker(scope, value);
  // A place a module owns says whose it is: a bare name among the
  // organization's own locations would read as one of them.
  const options = picker.options.map(({ contextTag, ...option }) => ({
    ...option,
    badge: storageModuleBadge(t, contextTag),
  }));
  return (
    <SearchableCombobox
      {...rest}
      value={value}
      options={options}
      loading={picker.loading}
      onSearchChange={picker.setSearch}
      // A search that failed says nothing about whether there are places: the
      // panel says it failed and offers a retry, not "no results".
      emptyMessage={
        picker.error ? (
          <LocationSearchFailed onRetry={picker.retry} />
        ) : (
          rest.emptyMessage
        )
      }
    />
  );
}
