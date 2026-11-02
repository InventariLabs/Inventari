import { expect, type Locator } from "@playwright/test";

/**
 * The phone the lists are measured on: a small Android, 360x800.
 *
 * A list opened on a phone must show a record, not only its controls, so the
 * first record has to start above the fold: clear of the bottom navigation,
 * with room left to read it.
 */
export const PHONE_WIDTH = 360;
export const PHONE_HEIGHT = 800;
// The bottom navigation covers the lowest ~64 px; a record that starts in the
// last 48 px above it shows its edge and nothing to read.
const BOTTOM_BAR = 64;
const READABLE = 48;
const FIRST_RECORD_MAX_Y = PHONE_HEIGHT - BOTTOM_BAR - READABLE;

/** Fails when the first record of the list at `path` starts below the fold. */
export async function expectFirstRecordAboveFold(
  path: string,
  first: Locator,
): Promise<void> {
  await expect(first).toBeVisible({ timeout: 15000 });
  // The page's own scroll position is zero on arrival; measure from there.
  const box = (await first.boundingBox())!;
  expect(
    box.y,
    `${path}: the first record starts at y=${Math.round(box.y)} of a ${PHONE_HEIGHT} px screen`,
  ).toBeLessThanOrEqual(FIRST_RECORD_MAX_Y);
}
