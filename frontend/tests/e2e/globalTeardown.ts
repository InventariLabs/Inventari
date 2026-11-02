import { request } from '@playwright/test';
import { ApiHelper } from './helpers/api';
import { ADMIN_EMAIL, ADMIN_PASSWORD } from './fixtures/credentials';

/**
 * Global teardown runs once after all tests.
 * Removes baseline seed data created in globalSetup.
 */
async function globalTeardown() {
  console.log('--- GLOBAL TEARDOWN START ---');
  const baseURL = process.env.VITE_API_URL || 'http://127.0.0.1:5173';

  const context = await request.newContext({ baseURL });

  try {
    const api = new ApiHelper(context);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    const token = authData.access_token;

    // Safety net: a test that changes the UI language and dies before its
    // cleanup would otherwise leave the shared account in that language,
    // breaking every English assertion in the *next* run.
    await api.setUserLanguage(token, 'en').catch(() => {});

    const itemIds = [
      process.env.E2E_ITEM_NORMAL_ID,
      process.env.E2E_ITEM_EXPIRING_ID,
      process.env.E2E_ITEM_EXPIRED_ID,
    ].filter(Boolean) as string[];

    for (const id of itemIds) {
      await api.deleteItem(token, id).catch(() => {});
    }

    const existingDocuments = await api.listDocuments(token);
    for (const d of existingDocuments) {
      if (d.number?.startsWith('E2E-')) {
        await api.cancelDocument(token, d.id).catch(() => {});
        await api.deleteDocument(token, d.id).catch(() => {});
      }
    }

    const existingStockTakes = await api.listStockTakes(token);
    for (const st of existingStockTakes) {
      if (st.name?.startsWith('E2E-')) {
        await api.deleteStockTake(token, st.id).catch(() => {});
      }
    }

    if (process.env.E2E_STORAGE_ID) {
      await api.deleteStorage(token, process.env.E2E_STORAGE_ID).catch(() => {});
    }
    if (process.env.E2E_CATEGORY_ID) {
      await api.deleteCategory(token, process.env.E2E_CATEGORY_ID).catch(() => {});
    }

    console.log('Cleaned up baseline seed data.');
  } catch (err) {
    console.error('Failed in globalTeardown:', err);
  } finally {
    await context.dispose();
  }

  console.log('--- GLOBAL TEARDOWN COMPLETE ---');
}

export default globalTeardown;
