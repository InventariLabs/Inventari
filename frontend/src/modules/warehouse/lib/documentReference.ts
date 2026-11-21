/**
 * What a document's reference means, when another module wrote it.
 *
 * A reference is free text a person types — a supplier's delivery note, an
 * invoice number — and the screens show it as it is. Two modules write one of
 * their own instead: a stock take names itself (`stock_take:<id>`) on the
 * adjustment it posts, and a recipe's cooking names the recipe
 * (`recipe:<id>`) on the issue it registers; issues registered before that
 * name the picking session (`picking:<id>`), which has no page of its own.
 * Read raw, those are an id nobody can follow; here each becomes words and,
 * where the app has a page for it and its module is on, the way to it.
 *
 * Only a known prefix followed by an id counts: "stock_take:week 4" typed by
 * a person stays their text.
 */

import { useEnabledModulesOptional } from "@/contexts/ModulesContext";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface ReferenceSource {
  /** The words that name the source, an i18n key. */
  labelKey: string;
  /** The page for it, or null when no screen opens one. */
  path: string | null;
  /** The module that has to be switched on for the page. */
  module: string;
}

const SOURCES: Record<string, (id: string) => ReferenceSource> = {
  stock_take: (id) => ({
    labelKey: "warehouse:references.stockTake",
    path: `/inventory/stock-takes/${id}/report`,
    module: "stock_takes",
  }),
  recipe: (id) => ({
    labelKey: "warehouse:references.recipeProduction",
    path: `/recipes/${id}`,
    module: "recipes",
  }),
  // A picking session: the cooking is told on the recipe, and no screen
  // opens one session of it.
  picking: () => ({
    labelKey: "warehouse:references.recipeProduction",
    path: null,
    module: "recipes",
  }),
};

/** A reference as a screen shows it: the words, and a page when there is one. */
export interface ReadReference {
  /** The i18n key naming another module's source, or null for typed text. */
  labelKey: string | null;
  /** The reference itself, for typed text. */
  text: string;
  path: string | null;
}

function sourceOf(reference: string): ReferenceSource | null {
  const colon = reference.indexOf(":");
  const source = colon > 0 ? SOURCES[reference.slice(0, colon)] : undefined;
  const id = reference.slice(colon + 1);
  return source && UUID.test(id) ? source(id) : null;
}

/**
 * How to read a document's reference on this organization: another module's
 * reference as words, with its page only while that module is on; anything
 * else as typed. Shared by the document page and the register row, so the
 * two never name one reference two ways.
 */
export function useDocumentReference(): (reference: string) => ReadReference {
  // The words need no module; the page is an addition, offered only while
  // the module that serves it is on.
  const enabledModules = useEnabledModulesOptional();
  return (reference) => {
    const source = sourceOf(reference);
    if (!source) return { labelKey: null, text: reference, path: null };
    return {
      labelKey: source.labelKey,
      text: reference,
      path: enabledModules.includes(source.module) ? source.path : null,
    };
  };
}
