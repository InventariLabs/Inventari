/**
 * Scenario 3: Spike test — sudden traffic burst
 *
 * Simulates e.g. morning rush when all users log in simultaneously.
 * Goal: find the breaking point (where degradation begins).
 */
import http from 'k6/http';
import { sleep, check } from 'k6';
import { SharedArray } from 'k6/data';
import { login, authHeaders, BASE_URL } from './auth.js';

const users = new SharedArray('users', function () {
  const csvPath = __ENV.USERS_CSV || '/users.csv';
  return open(csvPath)
    .split('\n')
    .slice(1)
    .filter(Boolean)
    .map((line) => {
      const [email, password] = line.split(',');
      return { email: email.trim(), password: password.trim() };
    });
});

export const options = {
  stages: [
    { duration: '30s', target: 10 },   // baseline
    { duration: '10s', target: 200 },  // sudden spike
    { duration: '3m', target: 200 },   // sustain under spike
    { duration: '10s', target: 10 },   // ramp-down
    { duration: '2m', target: 10 },    // check recovery
  ],
  thresholds: {
    http_req_duration: ['p(99)<3000'],
    http_req_failed: ['rate<0.05'],
  },
};

if (users.length === 0) {
  throw new Error(
    'users.csv is empty! Run first:\n' +
    '  docker compose exec backend uv run python seed_load_test_users.py --count 200'
  );
}
const vuUser = users[(__VU - 1) % users.length];
let vuToken = null;

export function setup() {}

export default function () {
  if (!vuToken) {
    vuToken = login(vuUser.email, vuUser.password);
    if (!vuToken) { sleep(5); return; }
  }
  const headers = authHeaders(vuToken);

  http.batch([
    ['GET', `${BASE_URL}/api/v1/items`, null, { headers, tags: { name: 'items/list' } }],
    ['GET', `${BASE_URL}/api/v1/locations`, null, { headers, tags: { name: 'storages/list' } }],
    ['GET', `${BASE_URL}/api/v1/items/expiring`, null, { headers, tags: { name: 'items/expiring' } }],
    ['GET', `${BASE_URL}/api/v1/stats/overview`, null, { headers, tags: { name: 'stats/overview' } }],
  ]);

  sleep(Math.random() * 2 + 0.5);
}
