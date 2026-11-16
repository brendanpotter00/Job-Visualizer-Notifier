// BL-01 (UI): the Pro card's button is right for each kind of visitor.
import { test, expect } from '@playwright/test';
import { makeUser, proButton, signIn } from './helpers';

test.describe('BL-01 the Pro button matches who is looking', () => {
  test('BL-01 signed out: Sign in to upgrade', async ({ page }) => {
    await page.goto('/pricing');
    await expect(proButton(page)).toHaveText('Sign in to upgrade');
    await expect(proButton(page)).toBeEnabled();
  });

  test('BL-01 a free user: Upgrade to Pro, enabled', async ({ context, page }) => {
    await signIn(context, makeUser('free'));
    await page.goto('/pricing');
    await expect(proButton(page)).toHaveText('Upgrade to Pro');
    await expect(proButton(page)).toBeEnabled();
  });

  test('BL-01 an admin: Included with your account, disabled', async ({ context, page }) => {
    await signIn(context, makeUser('admin'));
    await page.goto('/pricing');
    await expect(proButton(page)).toHaveText('Included with your account');
    await expect(proButton(page)).toBeDisabled();
  });
});
