import { cookieValue } from '../helpers/api';
import { test as base } from './base';
import { ADMIN_EMAIL, ADMIN_PASSWORD } from './credentials';

/**
 * Auth fixture — injects a fresh refresh_token cookie before every test
 * that depends on the ``authenticatedPage`` fixture.
 *
 * Each test gets its own POST /api/v1/auth/login call, giving every
 * parallel worker its own session_id (sid) and preventing the token
 * rotation race that occurs when workers share a single cookie.
 */
export const test = base.extend<{
  authenticatedPage: void;
}>({
  authenticatedPage: async ({ request, page, baseURL }, use) => {
    const loginResp = await request.post('/api/v1/auth/login', {
      form: {
        username: ADMIN_EMAIL,
        password: ADMIN_PASSWORD,
      },
    });
    if (!loginResp.ok()) {
      throw new Error(`Login failed: ${loginResp.status()} ${await loginResp.text()}`);
    }
    const refreshToken = await cookieValue(request, 'refresh_token');
    const cookieUrl = new URL(baseURL ?? 'http://127.0.0.1:5173');

    await page.context().addCookies([
      {
        name: 'refresh_token',
        value: refreshToken,
        url: cookieUrl.origin,
        httpOnly: true,
        secure: cookieUrl.protocol === 'https:',
        sameSite: 'Lax' as const,
      },
    ]);

    await use();
  },
});

export { expect } from '@playwright/test';
