import { expect, type Page } from "@playwright/test";

/**
 * A key i18next cannot resolve is rendered as the key itself: with a
 * namespace prefix when the namespace is unknown, and stripped down to the
 * bare dotted path when only the key is missing. Both shapes read as garbage
 * to a user, and neither shows up in an English run when the English bundle
 * happens to be complete.
 */
const NAMESPACED_KEY = /^[a-z_]+:[a-zA-Z0-9_.]+$/;
// A dotted path of two or more segments: "detail.rejectedBanner.someone".
// In practice this is the shape that actually shows up — i18next strips the
// namespace when it cannot resolve a key, so the namespaced form above is the
// rarer case (an unknown namespace, not an unknown key).
//
// Single-segment keys ("subtitle", "title") are indistinguishable from
// ordinary words and are not detectable this way.
const BARE_KEY = /^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_]+)+$/;
// Dotted lowercase strings that are legitimately shown to users.
const ALLOWED = /\.(pdf|csv|xlsx?|json|png|jpe?g|webp|svg|txt|zip)$/i;

/** Fail if any visible text on the page is an unresolved translation key. */
export async function expectNoRawI18nKeys(page: Page): Promise<void> {
  const suspects = await page.evaluate(
    ([namespacedSource, bareSource, allowedSource]) => {
      const namespaced = new RegExp(namespacedSource);
      const bare = new RegExp(bareSource);
      const allowed = new RegExp(allowedSource, "i");
      const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
      );
      const found: string[] = [];
      let node = walker.nextNode();
      while (node) {
        const text = (node.textContent ?? "").trim();
        if (
          text &&
          !allowed.test(text) &&
          (namespaced.test(text) || bare.test(text))
        ) {
          found.push(text);
        }
        node = walker.nextNode();
      }
      return [...new Set(found)];
    },
    [NAMESPACED_KEY.source, BARE_KEY.source, ALLOWED.source] as const,
  );

  expect(
    suspects,
    `Unresolved translation keys rendered at ${page.url()}`,
  ).toEqual([]);
}
