import i18n, { type BackendModule, type ReadCallback } from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import {
  SUPPORTED_LANGUAGES,
  isCommunityLanguage,
  type Language,
  resolveLang,
} from "./languages";

/**
 * The translations, one language at a time.
 *
 * These used to be fifty static imports plus an eager glob over every module's
 * bundle — all five languages of all of it, in the entry chunk, downloaded by
 * everyone including a visitor with no account. Measured: 1.3 MB of raw JSON
 * of which a reader uses a fifth, and the module half is the larger one
 * (920 kB against the core's 386 kB), which the report that opened this did
 * not know.
 *
 * A glob without `eager` gives one dynamic import per file, so the bundler
 * emits them as chunks of their own and the browser fetches the language it
 * needs. Which one that is, is known before the first render — it comes from
 * localStorage or the browser — so nothing flashes in English on the way.
 */
type Bundle = Record<string, unknown>;
type Loader = () => Promise<{ default: Bundle }>;

const coreLocales = import.meta.glob<{ default: Bundle }>("./locales/*/*.json");

const moduleLocales = import.meta.glob<{ default: Bundle }>(
  "../modules/*/i18n/*.json",
);

/**
 * `${language}/${namespace}` → the import that fetches it.
 *
 * A module's namespace is the module's own name: `t("equipment:...")` reaches
 * the file under `modules/equipment/i18n/`.
 */
const LOADERS: Record<string, Loader> = {};
const NAMESPACES = new Set<string>();

for (const [path, load] of Object.entries(coreLocales)) {
  const match = path.match(/locales\/(\w+)\/(\w+)\.json$/);
  if (!match) continue;
  const [, lang, ns] = match;
  LOADERS[`${lang}/${ns}`] = load;
  NAMESPACES.add(ns);
}

for (const [path, load] of Object.entries(moduleLocales)) {
  const match = path.match(/modules\/([^/]+)\/i18n\/(\w+)\.json$/);
  if (!match) continue;
  const [, ns, lang] = match;
  if (!SUPPORTED_LANGUAGES.includes(lang as Language)) continue;
  LOADERS[`${lang}/${ns}`] = load;
  NAMESPACES.add(ns);
}

/**
 * The namespaces this backend can serve a catalog for — the core locale
 * files and the module i18n directories.
 *
 * A catalog only lands for one of these, so they are exactly the namespaces
 * {@link onCatalogLoaded} can announce and the registry can re-apply the
 * standing overrides for. The i18n overrides gate reads this set to tell a
 * namespace the ordering guarantee reaches from one it does not.
 */
export function servedNamespaces(): Set<string> {
  return new Set(NAMESPACES);
}

/** A catalog that has just been merged into the i18next store. */
export type CatalogListener = (
  language: string,
  namespace: string,
  catalog: Record<string, unknown>,
) => void;

const catalogListeners = new Set<CatalogListener>();

/**
 * Called after i18next has merged a catalog, synchronously with the backend
 * handing it over.
 *
 * The module registry subscribes to keep its pristine snapshots and standing
 * overrides in step with a catalog that lands late. The subscription lives on
 * this side of the arrow because `config.ts` is reachable from the anonymous
 * attestation tree (`mutationFactory` imports it) and that tree must not reach
 * the registry — `check:public-bundle` enforces it.
 */
export function onCatalogLoaded(listener: CatalogListener): () => void {
  catalogListeners.add(listener);
  return () => {
    catalogListeners.delete(listener);
  };
}

/**
 * Fetches a bundle when i18next asks for one.
 *
 * A plugin rather than a `loadLanguage()` helper on purpose: four places
 * change the language — the selector, and three in the auth store — and a
 * helper is only as good as the call site that remembers to await it. i18next
 * asks for what it is missing, so every one of them works without knowing
 * this exists.
 */
const dynamicBundles: BackendModule = {
  type: "backend",
  init: () => {},
  read(language: string, namespace: string, callback: ReadCallback) {
    const load = LOADERS[`${language}/${namespace}`];
    // A namespace a language has no file for is not an error: the module may
    // ship four translations, and English behind it answers the fifth.
    if (!load) {
      callback(null, {});
      return;
    }
    load().then(
      (module) => {
        // `callback` hands the bundle to i18next synchronously, so by the
        // time it returns the catalog is in the store and the listeners see
        // the same state i18next does.
        callback(null, module.default as never);
        const catalog = module.default as Record<string, unknown>;
        catalogListeners.forEach((listener) => {
          listener(language, namespace, catalog);
        });
      },
      (error) => callback(error as Error, false),
    );
  },
};

/** Which language this reader will get, decided before anything is fetched. */
function detectLanguage(): Language {
  try {
    const stored = window.localStorage?.getItem("i18nextLng");
    if (stored) return resolveLang(stored);
  } catch {
    // A browser refusing storage is not a reason to fail to start.
  }
  return resolveLang(window.navigator?.language);
}

/**
 * Start i18next with the reader's language, and English behind it.
 *
 * Awaited in `main.tsx` before the first render: a `t()` call against a
 * language that has not arrived renders the key itself, and a screen of raw
 * keys is worse than a moment of nothing.
 */
export async function initI18n(): Promise<typeof i18n> {
  const lang = detectLanguage();

  await i18n
    .use(dynamicBundles)
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      lng: lang,
      fallbackLng: "en",
      defaultNS: "common",
      ns: [...NAMESPACES],
      preload: [lang],
      // The screens read their namespaces synchronously; everything they can
      // ask for is in memory by the time the first one mounts.
      react: { useSuspense: false },

      interpolation: {
        escapeValue: false,
      },

      // A t() call landing on a namespace node renders i18next's own error text
      // straight into the UI — `t("items:empty")` on the add-product gate printed
      // "key 'empty (pl)' returned an object instead of string", which on a phone
      // was the only text on the screen. Nothing failed, because rendering that
      // sentence is i18next's documented behaviour. In development and in tests
      // it now throws, so the mistake shows up where it is cheap; in production
      // it renders nothing rather than a line about the library.
      returnedObjectHandler: (key: string) => {
        if (import.meta.env.DEV) {
          throw new Error(
            `i18n: t("${key}") resolved to an object — point it at a leaf key`,
          );
        }
        return "";
      },

      detection: {
        order: ["localStorage", "navigator"],
        caches: ["localStorage"],
        lookupLocalStorage: "i18nextLng",
      },
    });

  // English behind it, but not in the way: it is the safety net for a key a
  // translation has not caught up with, and the gate that keeps the maintained
  // languages in step makes that rare. Waiting for it would put a second
  // 200 kB in front of the first render to cover a case that should not
  // happen; fetching it after costs the reader nothing. A community language
  // is the exception: it is expected to have gaps, and a screen with raw keys
  // in them is worse than the wait.
  if (lang !== "en") {
    const english = i18n.loadLanguages("en");
    if (isCommunityLanguage(lang)) await english;
    else void english;
  }

  return i18n;
}

export default i18n;
