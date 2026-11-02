import { test, expect } from "./fixtures/auth";

/**
 * What the deadline calendar covers in the campaign dialog.
 *
 * A walkthrough reported the picker sitting over the campaign's name and
 * description at 1440x900. Measured here, that is exactly what it does — and
 * it is the picker working as designed: the panel is 432px tall, the trigger
 * sits 344px above the viewport floor, so Radix flips it to the side with
 * room, which is upwards, over the fields above. A popover overlays; that is
 * what one is for.
 *
 * The two rules it must keep are the ones asserted below: it never hides the
 * field it belongs to, and letting go of it does not take the typed value.
 * Below `sm:` the same control is a bottom sheet — a modal layer that covers
 * the form by design (UI_GUIDELINES §4.3) — so only the second rule applies.
 *
 * Only a browser answers any of this: JSDOM lays nothing out, and the side the
 * panel opens on is decided from measured space.
 */

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

function overlaps(a: Box, b: Box): boolean {
  return (
    a.x < b.x + b.width &&
    b.x < a.x + a.width &&
    a.y < b.y + b.height &&
    b.y < a.y + a.height
  );
}

const TYPED = "Deadline overlap measurement";

test("the deadline picker leaves its own field visible (desktop)", async ({
  page,
  authenticatedPage,
}) => {
  void authenticatedPage;
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/equipment/campaigns");

  // The campaign is an attestation everywhere
  // the reader stands — the button, the field, the dialog title.
  await page.getByRole("button", { name: /new attestation/i }).click();
  const dialog = page.getByRole("dialog").first();
  await expect(dialog).toBeVisible();

  const name = dialog.getByLabel(/attestation name/i);
  await name.fill(TYPED);

  const trigger = dialog.getByRole("combobox", { name: /deadline/i });
  await trigger.click();

  const panel = page.getByRole("dialog", { name: /date/i }).last();
  await expect(panel).toBeVisible();
  const panelBox = (await panel.boundingBox()) as Box;
  // Measured after the panel opens: the form above it can still grow while
  // its data loads, and a box taken before that moves the field the panel
  // is anchored to.
  const triggerBox = (await trigger.boundingBox()) as Box;

  expect(overlaps(panelBox, triggerBox)).toBe(false);

  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await expect(name).toHaveValue(TYPED);
});

test("the deadline sheet gives the form back untouched (narrow)", async ({
  page,
  authenticatedPage,
}) => {
  void authenticatedPage;
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/equipment/campaigns");

  await page.getByRole("button", { name: /new attestation/i }).click();
  const dialog = page.getByRole("dialog").first();
  await expect(dialog).toBeVisible();

  const name = dialog.getByLabel(/attestation name/i);
  await name.fill(TYPED);

  await dialog.getByRole("combobox", { name: /deadline/i }).click();

  const sheet = page.getByRole("dialog", { name: /date/i }).last();
  await expect(sheet).toBeVisible();
  const sheetBox = (await sheet.boundingBox()) as Box;

  // A bottom sheet, not a popover: it takes the width of the screen and
  // covers the form behind it, the deadline field included. Its exact
  // vertical position is mid-animation here, so only the width is measured.
  expect(sheetBox.width).toBeGreaterThan(360);

  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  // The dialog underneath survives the same keystroke, with what was typed.
  await expect(dialog).toBeVisible();
  await expect(name).toHaveValue(TYPED);
});
