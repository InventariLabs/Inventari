import { test, expect } from "./fixtures/auth";

/**
 * Touch targets on the settings and app-store screens, measured at 390 px.
 *
 * WCAG 2.2 SC 2.5.8 asks every pointer target for 24x24 CSS px. JSDOM has no
 * layout, so a class assertion passes on a link that is still 15px tall; this
 * reads the rendered boxes. The shell (header, bottom bar) is out of scope --
 * it has its own measurements -- but everything inside `main` is measured,
 * the app store's category tabs among it. The page's primary actions are held
 * to the 44px the rest of the phone UI keeps.
 *
 * The file name keeps the word "responsive": the `mobile` project selects its
 * specs by that pattern (see playwright.config.ts).
 */
const FLOOR = 24;
const PRIMARY = 44;

/**
 * What must be on screen before the boxes are read: both screens fill in
 * after their queries answer, and a read taken on the skeleton measures
 * nothing. `primary` names the controls that carry the 44px floor.
 */
const SCREENS = [
  {
    name: "Settings",
    path: "/settings",
    ready: "main a[href^='/settings/'], main [role=switch]",
    primary: "",
  },
  {
    name: "App store",
    path: "/apps",
    ready: "main nav[aria-label='Filter modules'] button, main button",
    primary: "main button:not(nav button)",
  },
] as const;

for (const screen of SCREENS) {
  test.describe(`${screen.name} — touch targets`, () => {
    test.beforeEach(async ({ authenticatedPage }) => {
      void authenticatedPage;
    });

    test(`every control on ${screen.path} is at least ${FLOOR}x${FLOOR} at 390px`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(screen.path);
      await expect(page.locator("main h1, main h2").first()).toBeVisible({
        timeout: 15000,
      });
      await expect(
        page.locator(screen.ready).filter({ visible: true }).first(),
      ).toBeVisible({
        timeout: 15000,
      });

      const small = await page.evaluate(
        ({ floor, primarySelector, primary }) => {
          const selector =
            "a[href], button, input, select, textarea, [role=tab], [role=switch], [role=checkbox], [role=button]";
          const found: string[] = [];
          for (const el of Array.from(document.querySelectorAll(selector))) {
            const style = getComputedStyle(el);
            if (style.visibility === "hidden" || style.display === "none")
              continue;
            // The skip link is 1x1 until it takes focus, by design.
            if (el.closest(".sr-only") || el.classList.contains("sr-only"))
              continue;
            // The shell has its own measurements; the page's own navigation, a
            // filter's tabs among it, lives inside `main` and is measured here.
            if (!el.closest("main")) continue;
            const box = el.getBoundingClientRect();
            if (!box.width || !box.height) continue;
            const needs =
              primarySelector && el.matches(primarySelector) ? primary : floor;
            if (box.width < floor || box.height < needs) {
              const name = (
                el.getAttribute("aria-label") ||
                el.textContent ||
                el.tagName
              )
                .trim()
                .slice(0, 40);
              found.push(
                `${el.tagName.toLowerCase()} "${name}" ${Math.round(box.width)}x${Math.round(box.height)}`,
              );
            }
          }
          return found;
        },
        { floor: FLOOR, primarySelector: screen.primary, primary: PRIMARY },
      );

      expect(small).toEqual([]);
    });
  });
}
