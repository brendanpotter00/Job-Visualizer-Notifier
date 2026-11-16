// Billing UI helpers: fresh users (via ../ui_users.py, the same code path the
// API tier uses), signed-in contexts, and paying on Stripe's hosted Checkout.
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import type { BrowserContext, Page } from '@playwright/test';
import { expect } from '@playwright/test';
import { signInContext } from '../../shared/auth/storage_state';

const REPO_ROOT = path.resolve(__dirname, '../../..');
const PYTHON = path.join(REPO_ROOT, '.venv', 'bin', 'python');

export type UserKind = 'free' | 'admin' | 'subscriber';

export interface BillingUser {
  sub: string;
  email: string;
  userId: string;
  clockId?: string;
}

/** A brand-new user of `kind`, created through the backend (see ui_users.py). */
export function makeUser(kind: UserKind): BillingUser {
  const out = execFileSync(PYTHON, ['-m', 'e2e.billing.ui_users', kind], {
    cwd: REPO_ROOT,
    encoding: 'utf-8',
    timeout: 120_000,
  });
  return JSON.parse(out.trim().split('\n').pop() ?? '{}') as BillingUser;
}

/** Sign the test's own context in as `user`, before its first navigation. */
export async function signIn(context: BrowserContext, user: BillingUser): Promise<void> {
  await signInContext(context, { sub: user.sub, email: user.email });
}

/** The Pro card's main button. One per page; its label is the case's subject. */
export function proButton(page: Page) {
  return page.getByRole('button', { name: /Sign in to upgrade|Upgrade to Pro|Manage billing|Included with your account|Turning on Pro/ });
}

/**
 * Pay the open hosted Checkout with Stripe's 4242 test card.
 *
 * The form lives in Stripe's "Secure embedded form frame" (selectors probed
 * against the live page, 2026-11-15). Apple Pay / Google Pay / Link never
 * appear in headless Chromium, so the Card accordion is the only path.
 */
export async function payOnCheckout(page: Page, email: string): Promise<void> {
  await expect(page).toHaveURL(/^https:\/\/checkout\.stripe\.com\//, { timeout: 30_000 });
  const form = page.frameLocator('iframe[title="Secure embedded form frame"]');

  const emailInput = form.locator('#linkAuthentication-emailInput');
  if (await emailInput.isVisible().catch(() => false)) {
    if (!(await emailInput.inputValue())) await emailInput.fill(email);
  }
  const card = form.locator('#payment-numberInput');
  if (!(await card.isVisible().catch(() => false))) {
    await form.getByText('Card', { exact: true }).first().click();
  }
  await card.fill('4242424242424242');
  await form.locator('#payment-expiryInput').fill('12 / 34');
  await form.locator('#payment-cvcInput').fill('123');
  await form.locator('#payment-nameInput').fill('E2E Billing');
  const country = form.locator('#payment-countryInput');
  if (await country.isVisible().catch(() => false)) await country.selectOption('US');
  const zip = form.locator('#payment-postalCodeInput');
  if (await zip.isVisible().catch(() => false)) await zip.fill('10001');
  const linkOptIn = form.locator('#payment-linkOptInInput');
  if ((await linkOptIn.isVisible().catch(() => false)) && (await linkOptIn.isChecked())) {
    await linkOptIn.uncheck();
  }
  await form.locator('[data-testid="payment-form-submit-button"]').click();
}
