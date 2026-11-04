import { test, expect } from "./fixtures/auth";

/**
 * The demo bar stays short on a phone and on one line on a desktop, in each
 * of the five languages.
 *
 * A phone shows a one-sentence notice (`demo.noticeShort`) and the three
 * actions — the inbox link, the label sheet, "Start over" — beside it, so the
 * whole strip is two lines and the launcher's first row of tiles stays on an
 * 844 px screen. A desktop keeps the long sentence, the one about where the
 * demo's mail lands included, with the inbox link after it.
 *
 * The width of every label is per language — the German ones are the widest —
 * and a character count cannot say how far a translation wraps. Only the
 * rendered line count answers that, so this measures it in a browser at 360
 * and 390 px. The mocked status carries an inbox address, as a demo's always
 * does (DEMO_INBOX_URL); the link is checked too: a bar that said the sentence
 * without the way to the inbox would be half of what it owes.
 *
 * What the strip says is read back in the language under test: a notice still
 * showing the English catalog would otherwise be measured rather than
 * caught. The stack behind the test is not a demo stack and the interface
 * language the app applies is the account's own, so `init-status` and the user
 * payload are both answered from here — nothing the server keeps is touched,
 * unlike flipping `preferred_language` on the shared account.
 */

const LANGUAGES = [
  {
    code: "en",
    schedule: /every night/,
    warning: /real data/,
    inbox: /public inbox anyone can read/,
    short: /wiped nightly\. No real data/,
    inboxLink: "Open the inbox",
    inboxLinkShort: "Public inbox",
    startOver: "Start over",
  },
  {
    code: "pl",
    schedule: /co noc/,
    warning: /prawdziwych danych/,
    inbox: /publicznej skrzynki/,
    short: /czyszczone co noc\. Bez prawdziwych danych/,
    inboxLink: "Otwórz skrzynkę",
    inboxLinkShort: "Skrzynka publiczna",
    startOver: "Zacznij od nowa",
  },
  {
    code: "de",
    schedule: /jede Nacht/,
    warning: /echten Daten/,
    inbox: /öffentlichen Postfach/,
    short: /jede Nacht gelöscht\. Keine echten Daten/,
    inboxLink: "Postfach öffnen",
    inboxLinkShort: "Öffentliches Postfach",
    startOver: "Neu beginnen",
  },
  {
    code: "fr",
    schedule: /chaque nuit/,
    warning: /vraies données/,
    inbox: /boîte publique/,
    short: /effacée chaque nuit\. Pas de vraies données/,
    inboxLink: "Ouvrir la boîte",
    inboxLinkShort: "Boîte publique",
    startOver: "Recommencer",
  },
  {
    code: "es",
    schedule: /cada noche/,
    warning: /datos reales/,
    inbox: /buzón público/,
    short: /borrada cada noche\. Sin datos reales/,
    inboxLink: "Abrir el buzón",
    inboxLinkShort: "Buzón público",
    startOver: "Empezar de nuevo",
  },
];

const DEMO_INBOX_URL = "https://demo.test/mailpit/";
// On a phone the strip is a sentence and the actions line: two lines of 12 px
// text plus its padding, 72 px measured.
const PHONE_LINE_BUDGET = 2;

const VIEWPORTS = [
  // At 360 px the German actions no longer share one line, so the strip is
  // three lines tall there; the two-line budget is the 390 px one.
  { name: "a narrow phone", width: 360, height: 800, strip: 120 },
  { name: "a phone", width: 390, height: 844, strip: 80 },
  { name: "a desktop", width: 1280, height: 800, strip: 40 },
];

for (const viewport of VIEWPORTS) {
  test.describe(`Demo notice on ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    for (const language of LANGUAGES) {
      test(`the ${language.code} notice stays within the budget`, async ({
        page,
        authenticatedPage,
      }) => {
        await page.context().route("**/api/v1/auth/init-status", (route) =>
          route.fulfill({
            json: {
              is_initialized: true,
              is_demo: true,
              demo_inbox_url: DEMO_INBOX_URL,
            },
          }),
        );
        await page.context().route("**/api/v1/auth/me", async (route) => {
          const response = await route.fetch();
          const user = await response.json();
          user.preferred_language = language.code;
          await route.fulfill({ response, json: user });
        });

        await page.goto("/");
        const notice = page.locator('div.sticky [role="status"]').first();

        const isPhone = viewport.width < 640;
        const strip = notice.locator("xpath=..");
        const inboxLink = notice.locator("xpath=following-sibling::a");

        // The bar speaks the language under test, and says where the mail
        // lands only on a desktop: a phone keeps the short sentence and the
        // link's short name.
        if (isPhone) {
          await expect(notice).toContainText(language.short, {
            timeout: 15000,
          });
          await expect(inboxLink).toHaveText(language.inboxLinkShort);
        } else {
          await expect(notice).toContainText(language.schedule, {
            timeout: 15000,
          });
          await expect(notice).toContainText(language.warning, {
            timeout: 15000,
          });
          await expect(notice).toContainText(language.inbox, {
            timeout: 15000,
          });
          await expect(inboxLink).toHaveText(language.inboxLink);
        }
        // …and the way to the inbox, one unbroken link, on both.
        await expect(inboxLink).toHaveAttribute("href", DEMO_INBOX_URL);
        // Counted from the text's own line boxes: the link keeps a 24 px
        // target on a phone, which is taller than its 16 px line.
        const linkLines = await inboxLink.evaluate((element) => {
          const range = document.createRange();
          range.selectNodeContents(element);
          return new Set(
            Array.from(range.getClientRects()).map((rect) =>
              Math.round(rect.top),
            ),
          ).size;
        });
        expect(
          Math.round(linkLines),
          `${language.code} inbox link is split across lines`,
        ).toBe(1);

        const { lines, width, stripHeight, position } = await notice.evaluate(
          (element) => {
            const lineHeight = parseFloat(getComputedStyle(element).lineHeight);
            const strip = element.closest("div.sticky") as HTMLElement;
            return {
              lines: Math.round(
                element.getBoundingClientRect().height / lineHeight,
              ),
              width: window.innerWidth,
              stripHeight: strip.getBoundingClientRect().height,
              position: getComputedStyle(strip).position,
            };
          },
        );
        expect(width, "the viewport is what the test states").toBe(
          viewport.width,
        );

        if (!isPhone) {
          // A desktop keeps the strip on one line, under the bar as the page scrolls.
          expect(lines, `${language.code} wraps on a desktop`).toBe(1);
          expect(position).toBe("sticky");
          return;
        }
        expect(
          lines,
          `${language.code} notice wraps to ${lines} lines at ${width} px`,
        ).toBeLessThanOrEqual(PHONE_LINE_BUDGET);
        expect(
          stripHeight,
          `${language.code} strip is ${stripHeight} px tall at ${width} px`,
        ).toBeLessThanOrEqual(viewport.strip);
        // Both actions stay within reach of a thumb: on screen, not cut off.
        for (const name of [language.startOver, inboxLink]) {
          const target =
            typeof name === "string"
              ? strip.getByRole("button", { name })
              : name;
          await expect(target).toBeInViewport({ ratio: 1 });
        }
        // It scrolls away with the page: it must not cover a camera
        // viewfinder or a focused field on the way down.
        expect(position).toBe("static");
      });
    }
  });
}
