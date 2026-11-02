/**
 * The modules that declare `standalone`, by name.
 *
 * The live registry only holds modules the organization has enabled — a
 * module registers itself when its chunk is imported, and only enabled ones
 * are imported — so it cannot say which switched-off modules *could* stand
 * alone. Showing just one module needs that answer exactly when none is enabled, to tell
 * the reader what to switch on. The list is kept here and pinned by
 * `standaloneGate.test.ts` against what the manifests declare, so a module
 * gaining or losing the declaration fails a build until this follows.
 */
export const STANDALONE_MODULE_NAMES: readonly string[] = [
  "equipment",
  "maker",
  "recipes",
  "shopping_lists",
  "warehouse",
];
