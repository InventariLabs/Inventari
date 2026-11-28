import type { Page } from "@playwright/test";

/**
 * A scanner typing: every key of the code, then Enter, with the focus nowhere
 * in particular. The keys are raised in the page in one go, the way a scanner
 * sends them (the app takes a burst whose keys come under 50 ms apart as a
 * scan): sent one by one from outside, a busy machine stretches a gap past
 * that and the code arrives cut in two, which is the app doing what it should.
 *
 * Nothing waits here: assert first that the screen asking for the code shows.
 */
export async function wedgeScan(page: Page, reading: string) {
  await page.evaluate((code) => {
    (document.activeElement as HTMLElement | null)?.blur();
    const send = (key: string) => {
      document.body.dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
      );
    };
    for (const key of code) send(key);
    send("Enter");
  }, reading);
}
