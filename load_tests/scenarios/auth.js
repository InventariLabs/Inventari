/**
 * Inventari k6 — auth helpers
 * Reusable login helpers shared across all scenarios.
 */
import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

/**
 * Logs in a user and returns the access token.
 * @param {string} email
 * @param {string} password
 * @returns {string} access_token or throws on failure
 */
export function login(email, password) {
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    { username: email, password: password },
    { tags: { name: 'auth/login' } },
  );

  check(res, {
    'login 200': (r) => r.status === 200,
    'login has token': (r) => r.json('access_token') !== undefined,
  });

  return res.json('access_token');
}

/**
 * Returns headers with Bearer token.
 */
export function authHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  };
}

export { BASE_URL };
