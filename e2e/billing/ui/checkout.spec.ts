// BL-02: our button -> hosted Checkout -> 4242 -> signed webhook -> "You’re on Pro."
// BL-03: the post-sign-in landing (/pricing?intent=pro) opens Checkout by itself.
import { test, expect } from '@playwright/test';
import { makeUser, payOnCheckout, proButton, signIn } from './helpers';

test.describe('BL-02 paying on Stripe Checkout turns Pro on', () => {
  test('BL-02 Upgrade -> pay 4242 -> back on /pricing as Pro', async ({ context, page }) => {
    const user = makeUser('free');
    await signIn(context, user);
    await page.goto('/pricing');
    await expect(proButton(page)).toHaveText('Upgrade to Pro');
    await proButton(page).click();

    await payOnCheckout(page, user.email);

    await expect(page).toHaveURL(/127\.0\.0\.1:3204\/pricing\?checkout=success/, { timeout: 90_000 });
    await expect(page.getByText('You’re on Pro.')).toBeVisible({ timeout: 60_000 });
    await expect(proButton(page)).toHaveText('Manage billing');
    await expect(page.getByRole('link', { name: 'Account' })).toBeVisible();
  });
});

test.describe('BL-03 the sign-in return lands in Checkout', () => {
  // The Auth0 redirect itself is covered by HomeRouteReturnTo.test.tsx.
  test('BL-03 /pricing?intent=pro opens Checkout without a click', async ({ context, page }) => {
    await signIn(context, makeUser('free'));
    await page.goto('/pricing?intent=pro');
    await expect(page).toHaveURL(/^https:\/\/checkout\.stripe\.com\//, { timeout: 30_000 });
  });
});
