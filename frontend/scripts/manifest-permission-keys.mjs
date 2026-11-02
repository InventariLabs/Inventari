/**
 * The i18n keys a backend manifest declares implicitly.
 *
 * A permission written as a bare string — `"stats:export"` — carries no
 * `label_key` field; the backend synthesises `<module>:permissions.<action>`
 * when the field is absent (PermissionDef in module_manifest_schema.py). The
 * drift gate looks for values under `*_key`, so the shorthand slipped past it
 * entirely: the roles screen fell back to rendering the raw key and nothing
 * reported the missing translation.
 *
 * Its own file because check-i18n-keys.mjs runs its work at import time, and a
 * spec that imports it would run the whole gate.
 */
export function shorthandPermissionKeys(permissions, moduleName) {
  const out = [];
  for (const entry of permissions) {
    if (typeof entry !== "string") continue;
    const [namespace, ...rest] = entry.split(":");
    if (rest.length === 0) continue;
    // A key outside the module's own namespace is a dependency statement —
    // `recipes` naming `items:read` says what it reads, and the backend keeps
    // such keys out of the module's catalog section because the system section
    // already defines them. No module translation is owed for those.
    if (namespace !== moduleName) continue;
    out.push(`${namespace}:permissions.${rest.join("_")}`);
  }
  return out;
}
