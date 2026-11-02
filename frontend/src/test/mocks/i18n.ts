import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import { act } from "@testing-library/react";
import { vi } from "vitest";

/**
 * The unit suite runs the real i18next, not a stand-in.
 *
 * What used to live here was a ~120-line reimplementation of i18next —
 * its own key resolver, its own interpolation, and a hand-rolled Polish
 * plural rule (count 2–4 → _few) that could never fire because only the
 * English bundles were loaded. Every translation defect was therefore
 * invisible to 2335 tests: plural forms, interpolation and namespace
 * fallback were exercised by mock code, not by the code that ships.
 *
 * English stays the default language so existing text selectors keep
 * working. Tests that care about translation switch with
 * {@link withLanguage} and are put back to English afterwards.
 */

type GlobModule = { default: Record<string, unknown> };

/** Every interface language the app ships, so a test can ask for any of the
 *  typography that differs between them — French keeps a space before "%". */
const TEST_LANGUAGES = ["en", "pl", "de", "fr", "es", "pt"] as const;
type TestLanguage = (typeof TEST_LANGUAGES)[number];

const coreLocales = import.meta.glob<GlobModule>(
  "../../i18n/locales/*/*.json",
  {
    eager: true,
  },
);
const moduleLocales = import.meta.glob<GlobModule>(
  "../../modules/*/i18n/*.json",
  { eager: true },
);

const resources: Record<string, Record<string, unknown>> = {};

function addBundle(lang: string, namespace: string, bundle: unknown) {
  if (!TEST_LANGUAGES.includes(lang as TestLanguage)) return;
  resources[lang] ??= {};
  resources[lang][namespace] = bundle;
}

for (const path in coreLocales) {
  const match = path.match(/locales\/([^/]+)\/([^/]+)\.json$/);
  if (match) addBundle(match[1], match[2], coreLocales[path].default);
}

for (const path in moduleLocales) {
  const match = path.match(/modules\/([^/]+)\/i18n\/([^/]+)\.json$/);
  if (match) addBundle(match[2], match[1], moduleLocales[path].default);
}

export const DEFAULT_TEST_LANGUAGE: TestLanguage = "en";

i18next.use(initReactI18next).init({
  resources: resources as Record<
    string,
    Record<string, Record<string, string>>
  >,
  lng: DEFAULT_TEST_LANGUAGE,
  fallbackLng: "en",
  defaultNS: "common",
  interpolation: { escapeValue: false },
  // Parity with src/i18n/config.ts: with suspense on (the react-i18next
  // default) useTranslation suspends, and the resolution lands outside
  // every test's act as "A suspended resource finished loading" noise.
  react: { useSuspense: false },
  // Keep the reporting quiet but let a missing key still render as the key,
  // which is what production does and what several tests assert.
  saveMissing: false,
});

/**
 * A real translator bound to *namespace*, for components that take `t` as a
 * prop. Stubbing that prop as `(key) => key` turns every assertion on the
 * rendered label into an assertion on the key, which passes whether the
 * translation exists or not.
 */
export function tFor(namespace: string) {
  return i18next.getFixedT(null, namespace);
}

/** Render *body* with the interface in *language*, then restore English. */
export async function withLanguage(
  language: TestLanguage,
  body: () => void | Promise<void>,
): Promise<void> {
  // act-wrapped: the finally branch switches the language back while the
  // body's components are still mounted — RTL's cleanup runs only after
  // afterEach — so a bare changeLanguage re-rendered them outside act.
  await act(async () => {
    await i18next.changeLanguage(language);
  });
  try {
    await body();
  } finally {
    await act(async () => {
      await i18next.changeLanguage(DEFAULT_TEST_LANGUAGE);
    });
  }
}

// The app's own config module runs LanguageDetector and writes to
// localStorage. Hand tests the instance initialised above instead.
vi.mock("../../i18n/config", () => ({
  default: i18next,
  // The real module announces landed catalogs; the registry subscribes at
  // import time. The mock's resources are loaded eagerly, so no catalog ever
  // lands through this path in tests.
  onCatalogLoaded: () => () => {},
  // The real module derives this from the same two globs above; answer from
  // the resources already loaded, so a gate can ask which namespaces a
  // catalog could land in.
  servedNamespaces: () =>
    new Set(Object.values(resources).flatMap((byNs) => Object.keys(byNs))),
  __esModule: true,
}));

export default i18next;
