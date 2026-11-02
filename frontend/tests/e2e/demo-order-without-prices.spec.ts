import { test, expect } from "./fixtures/base";

/**
 * A demo visitor can finish an order they confirmed without prices.
 *
 * The demo's workflow holds every order it cannot show to be under its limit,
 * and the visitor is the only person who can sign in, so the order used to wait
 * for good while the screen showed its total as 0.00. This walks what they do,
 * from "Try the demo" on the sign-in page to a confirmed order.
 *
 * It needs an instance built as the demo (`manage.py demo reset`, then
 * `demo fill-pool`, with INVENTARI_DEMO on) and passes over any other, which
 * has no sandbox to open. Each run claims a sandbox of its own and leaves the
 * rest of the instance alone. docs/DEMO.md says how to build one.
 */
test("a visitor confirms an order without prices and sees it through", async ({
  page,
  request,
}) => {
  const status = await request.get("/api/v1/auth/init-status");
  test.skip(
    !(await status.json()).is_demo,
    "needs an instance built as the demo",
  );

  await page.goto("/login");
  await page.getByRole("button", { name: /try the demo/i }).click();
  await expect(page).toHaveURL(/\/launcher/, { timeout: 30000 });

  await page.goto("/purchase-orders");
  await page
    .getByRole("button", { name: /create order/i })
    .first()
    .click();
  const form = page.getByRole("dialog", { name: /purchase order/i });
  await form.getByRole("combobox", { name: /supplier/i }).click();
  await page
    .getByRole("button", { name: "Northgate IT Distribution", exact: true })
    .click();
  await form.getByRole("combobox", { name: /product/i }).fill("Natural Yoghurt");
  await page
    .getByRole("option", { name: /natural yoghurt/i })
    .first()
    .click();
  // A line with no price is nothing to total: no 0.00 before the order exists.
  await expect(form.getByText(/^0\.00/)).toHaveCount(0);
  await form.getByRole("button", { name: /create order/i }).click();
  await expect(form).toBeHidden();

  // The list, then the order: neither calls it worth nothing.
  const row = page.getByRole("row").filter({ hasText: /no price yet/i });
  await expect(row).toHaveCount(1);
  await row.getByRole("button", { name: /^PO\// }).click();
  await expect(page.getByText(/no price yet/i).first()).toBeVisible();
  await expect(page.getByText(/natural yoghurt/i)).toBeVisible();
  await expect(page.getByText(/0\.00/)).toHaveCount(0);

  await page.getByRole("button", { name: /^confirm$/i }).click();
  const dialog = page.getByRole("alertdialog");
  // Why it needs approval, and that the visitor can see it through.
  await expect(dialog).toContainText(/total is not known/i);
  await expect(dialog).toContainText(/add the prices first/i);
  await expect(dialog).toContainText(/approval queue/i);
  await expect(dialog).not.toContainText(/nobody can decide/i);
  await dialog.getByRole("button", { name: /^confirm$/i }).click();
  await expect(page.getByText(/waiting for approval/i).first()).toBeVisible();

  // The demo's workflow has two stages, and the visitor decides each.
  for (const stage of ["Team lead", "Finance"]) {
    await page
      .getByRole("button", { name: /^approve$/i })
      .first()
      .click();
    const decide = page.getByRole("alertdialog");
    await decide.getByRole("button", { name: /^approve request$/i }).click();
    await expect(decide, `the ${stage} stage`).toBeHidden();
  }
  await expect(page.getByText(/^confirmed$/i).first()).toBeVisible();
  await expect(page.getByText(/nobody can decide/i)).toHaveCount(0);
});
