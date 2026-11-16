// BL-11: a subscriber's "Manage billing" opens the Stripe billing portal.
import { test, expect } from '@playwright/test';
import { makeUser, proButton, signIn } from './helpers';

test.describe('BL-11 Manage billing opens the portal', () => {
  test('BL-11 a subscriber is sent to billing.stripe.com', async ({ context, page }) => {
    await signIn(context, makeUser('subscriber'));
    await page.goto('/pricing');
    await expect(proButton(page)).toHaveText('Manage billing');
    await proButton(page).click();
    await expect(page).toHaveURL(/^https:\/\/billing\.stripe\.com\//, { timeout: 30_000 });
  });
});
