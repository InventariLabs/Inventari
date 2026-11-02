/**
 * Scenario 2: Write-heavy — storage management
 *
 * Simulates: creating storage locations, adding items, consuming stock,
 * and moving items between locations.
 *
 * BEFORE running, seed test users:
 *   docker compose exec backend uv run python seed_load_test_users.py --count 40
 *
 * Run:
 *   docker compose -f docker-compose.loadtest.yml run --rm k6 \
 *     run /scenarios/write_operations.js \
 *     -e BASE_URL=https://your-domain.com
 */
import http from 'k6/http';
import { sleep, check, group } from 'k6';
import { Rate, Counter } from 'k6/metrics';
import { SharedArray } from 'k6/data';
import { login, authHeaders, BASE_URL } from './auth.js';

const writeErrors = new Rate('write_error_rate');
const itemsCreated = new Counter('items_created');
const storagesCreated = new Counter('storages_created');

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
    { duration: '1m', target: 20 },
    { duration: '3m', target: 20 },
    { duration: '2m', target: 40 },
    { duration: '3m', target: 40 },
    { duration: '1m', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<1200'],
    write_error_rate: ['rate<0.01'],
  },
};

if (users.length === 0) {
  throw new Error(
    'users.csv is empty! Run first:\n' +
    '  docker compose exec backend uv run python seed_load_test_users.py --count 40'
  );
}
const vuUser = users[(__VU - 1) % users.length];
let vuToken = null;
let vuStorageIds = [];

const ITEM_NAMES = [
  'UHT Milk', 'Toast Bread', 'Butter Extra', 'Natural Yogurt',
  'Yellow Cheese', 'Penne Pasta', 'Tomato Sauce', 'Ground Coffee',
];

function randStr(n = 5) {
  return Math.random().toString(36).substring(2, 2 + n);
}

function randomFutureDate(minDays = 5, maxDays = 365) {
  const d = new Date();
  d.setDate(d.getDate() + Math.floor(Math.random() * (maxDays - minDays) + minDays));
  return d.toISOString().split('T')[0];
}

export function setup() {}

export default function () {
  // Login on first call per VU
  if (!vuToken) {
    vuToken = login(vuUser.email, vuUser.password);
    if (!vuToken) {
      console.error(`VU ${__VU}: failed to log in as ${vuUser.email}`);
      sleep(5);
      return;
    }
    // Fetch storage locations for this user's organisation
    const r = http.get(`${BASE_URL}/api/v1/locations`, { headers: authHeaders(vuToken) });
    if (r.status === 200) {
      vuStorageIds = r.json().map((s) => s.id);
    }
  }
  const headers = authHeaders(vuToken);
  let storageIds = [...vuStorageIds];

  // --- Create storage location ---
  group('Create storage location', () => {
    const r = http.post(
      `${BASE_URL}/api/v1/locations`,
      JSON.stringify({ name: `Test Loc ${randStr()}`, description: 'k6 test' }),
      { headers, tags: { name: 'storages/create' } },
    );
    const ok = check(r, { 'storage 201': (res) => res.status === 201 });
    writeErrors.add(!ok);
    if (ok) {
      storagesCreated.add(1);
      storageIds.push(r.json('id'));
    }
  });

  sleep(0.5);

  if (storageIds.length === 0) {
    sleep(2);
    return;
  }

  // --- Add items ---
  const createdItemIds = [];
  group('Add items', () => {
    const count = Math.floor(Math.random() * 4) + 2; // 2–5 items
    for (let i = 0; i < count; i++) {
      const storageId = storageIds[Math.floor(Math.random() * storageIds.length)];
      const r = http.post(
        `${BASE_URL}/api/v1/items`,
        JSON.stringify({
          name: `${ITEM_NAMES[Math.floor(Math.random() * ITEM_NAMES.length)]} ${randStr(3)}`,
          location_id: storageId,
          quantity: Math.floor(Math.random() * 10) + 1,
          expiry_date: randomFutureDate(),
        }),
        { headers, tags: { name: 'items/create' } },
      );
      const ok = check(r, { 'item 201': (res) => res.status === 201 });
      writeErrors.add(!ok);
      if (ok) {
        itemsCreated.add(1);
        createdItemIds.push(r.json('id'));
      }
      sleep(0.2);
    }
  });

  sleep(1);

  // --- Consume one item ---
  group('Consume item', () => {
    if (createdItemIds.length === 0) return;
    const itemId = createdItemIds[0];
    const r = http.patch(
      `${BASE_URL}/api/v1/items/${itemId}/consume`,
      JSON.stringify({ quantity: 1 }),
      { headers, tags: { name: 'items/consume' } },
    );
    check(r, { 'consume 200': (res) => res.status === 200 });
  });

  sleep(1);

  // --- Move item ---
  group('Move item', () => {
    if (createdItemIds.length < 1 || storageIds.length < 2) return;
    const itemId = createdItemIds[Math.floor(Math.random() * createdItemIds.length)];
    const targetStorage = storageIds[Math.floor(Math.random() * storageIds.length)];
    const r = http.patch(
      `${BASE_URL}/api/v1/items/${itemId}/move`,
      JSON.stringify({ to_location_id: targetStorage }),
      { headers, tags: { name: 'items/move' } },
    );
    check(r, { 'move 200': (res) => [200, 400].includes(res.status) });
  });

  sleep(Math.random() * 2 + 1);

  // After write operations — simulate dashboard refresh (every 3 iterations)
  // Tests that write + immediate read-stats does not cause race conditions or timeouts
  if (__ITER % 3 === 0) {
    group('Refresh stats after writes', () => {
      const r = http.get(`${BASE_URL}/api/v1/stats/overview`, {
        headers,
        tags: { name: 'stats/overview' },
      });
      check(r, { 'overview after write 200': (res) => res.status === 200 });
    });
    sleep(0.5);
  }
}
