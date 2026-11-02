import { useQueries } from "@tanstack/react-query";

import { modulesApi, type ModuleSettingsField } from "@/lib/api/modules";
import { queryKeys } from "@/hooks/queries/keys";

/** A settings path as the journal prints it → the key its catalogue names it by. */
export type SettingTitleKeys = Record<string, string>;

function collect(
  fields: Record<string, ModuleSettingsField> | undefined,
  prefix: string,
  out: SettingTitleKeys,
): void {
  for (const [name, field] of Object.entries(fields ?? {})) {
    const path = prefix ? `${prefix}.${name}` : name;
    if (field.title_key) out[path] = field.title_key;
    collect(field.properties, path, out);
  }
}

/**
 * How each module's settings call themselves, for the rows of the journal.
 *
 * A module's settings schema carries the ``title_key`` of every field — the
 * same key the settings screen renders — and the journal row for a settings
 * change knew nothing about it: it tidied the stored `snake_case` into "Allow
 * admin self approve", words that appear on no screen. Only the modules the
 * visible rows mention are fetched, and through the same query key the
 * settings screen uses, so opening the journal after changing a setting does
 * not ask the server the same question twice.
 */
export function useModuleSettingTitles(
  moduleNames: (string | null)[],
): Record<string, SettingTitleKeys> {
  const names = [
    ...new Set(moduleNames.filter((name): name is string => Boolean(name))),
  ].sort();

  const results = useQueries({
    queries: names.map((name) => ({
      queryKey: queryKeys.modules.settings(name),
      queryFn: () => modulesApi.getSettings(name),
      // A module's schema moves with a deployment, not while a reader scrolls.
      staleTime: 5 * 60_000,
      retry: false,
    })),
  });

  const titles: Record<string, SettingTitleKeys> = {};
  names.forEach((name, index) => {
    const schema = results[index]?.data?.settings_schema;
    if (!schema) return;
    const out: SettingTitleKeys = {};
    collect(schema.properties, "", out);
    titles[name] = out;
  });
  return titles;
}
