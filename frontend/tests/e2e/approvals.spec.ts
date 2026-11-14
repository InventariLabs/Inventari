import { test, expect } from "./fixtures/auth";
import { ApiHelper } from "./helpers/api";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";

test.describe("Approvals — workflows page & CRUD", () => {
  test.describe.configure({ mode: "serial" });

  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    await api.toggleModule(token, "approvals", true).catch(() => {});

    await api.cleanupApprovals(token);

    const existing = await api.listWorkflows(token);
    for (const w of existing) {
      if (w.name.startsWith("E2E-")) {
        await api.deleteWorkflow(token, w.id).catch(() => {});
      }
    }
  });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/approvals/workflows");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("workflows page loads with Create Workflow button", async ({
    page,
    authenticatedPage,
  }) => {
    const btn = page.getByRole("button", { name: /create workflow/i }).first();
    await expect(btn).toBeVisible({ timeout: 15000 });
  });

  test("workflows page heading is visible", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(
      page
        .locator("h1, h2")
        .filter({ hasText: /workflow/i })
        .first(),
    ).toBeVisible({ timeout: 15000 });
  });

  test("navigation bar has Dashboard and Workflows links", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.getByRole("link", { name: /dashboard/i })).toBeVisible({
      timeout: 15000,
    });
    await expect(page.getByRole("link", { name: /workflows/i })).toBeVisible({
      timeout: 10000,
    });
  });

  test("opens create workflow form", async ({ page, authenticatedPage }) => {
    const createBtn = page
      .getByRole("button", { name: /create workflow/i })
      .first();
    await expect(createBtn).toBeVisible({ timeout: 10000 });
    await createBtn.click();

    await expect(page.getByPlaceholder("e.g. Standard Approval")).toBeVisible({
      timeout: 10000,
    });
  });

  test("creates workflow via UI and verifies in list", async ({
    page,
    authenticatedPage,
  }) => {
    const createBtn = page
      .getByRole("button", { name: /create workflow/i })
      .first();
    await expect(createBtn).toBeVisible({ timeout: 10000 });
    await createBtn.click();

    const nameInput = page.locator('[data-testid="workflow-name-input"]');
    await expect(nameInput).toBeVisible({ timeout: 10000 });

    const name = `E2E-CRUD-${Date.now()}`;
    await nameInput.fill(name);

    // Whose submissions it holds has no default: the save waits for it.
    await page.getByRole("combobox", { name: /who it applies to/i }).click();
    await page.getByRole("option", { name: /^everyone$/i }).click();

    // A new stage names people; this one is left to anyone with the grant.
    await page.getByRole("combobox", { name: /who decides/i }).click();
    await page.getByRole("option", { name: /anyone who may approve/i }).click();

    const submitBtn = page.locator('[data-testid="workflow-submit-btn"]');
    await expect(submitBtn).toBeVisible({ timeout: 5000 });
    await submitBtn.click();

    // A successful save closes the form and lists the workflow; a refused one
    // leaves the form open, which fails here instead of passing unnoticed.
    await expect(nameInput).toBeHidden({ timeout: 10000 });
    await expect(page.getByText(name)).toBeVisible({ timeout: 10000 });

    const workflows = await api.listWorkflows(token);
    const created = workflows.find((w) => w.name === name);
    expect(created, `workflow "${name}" is in the API list`).toBeDefined();
    if (created) {
      await api.deleteWorkflow(token, created.id).catch(() => {});
    }
  });

  test("cancel button discards form", async ({ page, authenticatedPage }) => {
    const createBtn = page
      .getByRole("button", { name: /create workflow/i })
      .first();
    await expect(createBtn).toBeVisible({ timeout: 10000 });
    await createBtn.click();

    const name = `E2E-Cancel-${Date.now()}`;
    await page.getByPlaceholder("e.g. Standard Approval").fill(name);
    await page.getByRole("button", { name: /cancel/i }).click();
    await expect(page.getByPlaceholder("e.g. Standard Approval")).toBeHidden({ timeout: 10000 });

    const workflows = await api.listWorkflows(token);
    const leaked = workflows.find((w) => w.name === name);
    expect(leaked).toBeUndefined();
  });
});

test.describe("Approvals — dashboard", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page, authenticatedPage }) => {
    await page.goto("/approvals");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
  });

  test("approvals dashboard loads with heading", async ({
    page,
    authenticatedPage,
  }) => {
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });

  test("shows empty requests state or tabs", async ({
    page,
    authenticatedPage,
  }) => {
    await page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
    const hasEmpty = await page
      .getByText(/no pending.*request|no approval.*request/i)
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    const hasTabs = await page
      .getByRole("tab", { name: /all/i })
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    const hasContent = await page
      .locator("h1, h2, table, [role='list']")
      .first()
      .isVisible({ timeout: 5000 })
      .catch(() => false);
    expect(hasEmpty || hasTabs || hasContent).toBeTruthy();
  });

  test("has search input for requests", async ({ page, authenticatedPage }) => {
    await expect(page.getByPlaceholder(/search by name, number or type/i)).toBeVisible({
      timeout: 15000,
    });
  });
});

// ── New: reject, multi-stage, workflow update, filtering ────────────────

test.describe("Approvals — reject flow", () => {
  test.describe.configure({ mode: "serial" });

  let api: ApiHelper;
  let token: string;
  let workflowId: string;
  let requestId: string;
  let storageId: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    await api.toggleModule(token, "approvals", true).catch(() => {});
    await api.toggleModule(token, "warehouse", true).catch(() => {});
    // Its own location: the first one of the shared tenant belongs to
    // whichever parallel spec deletes it first.
    storageId = (
      await api.createStorage(token, {
        name: `E2E-Approvals-Reject-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      })
    ).id;

    await api.cleanupApprovals(token);

    try {
      const wf = await api.createWorkflow(token, {
        target_type: "document",
        is_active: true,
        name: `E2E-Reject-${Date.now()}`,
        stages: [
          { order: 1, label: "Review", role: "manager", approver_user_ids: [] },
        ],
      });
      workflowId = wf.id;
    } catch {
      // workflow creation may fail if stale requests block the target_type
    }
  });

  test.afterAll(async () => {
    if (token && workflowId) {
      await api.deleteWorkflow(token, workflowId).catch(() => {});
    }
    if (token && storageId) {
      await api.deleteStorage(token, storageId).catch(() => {});
    }
  });

  test("creates workflow for document approval", async () => {
    expect(workflowId, "the workflow the setup created").toBeTruthy();
  });

  test("rejects an approval request via API", async () => {
    // Create a document to trigger approval
    const doc = await api.createIntDocumentWithStock(token, {
      source_location_id: storageId,
      target_location_id: storageId,
      lines: [{ name: "E2E-Reject-Item", expected_quantity: 1 }],
    });

    await api.confirmDocument(token, doc.id);

    try {
      await api.requestDocumentApproval(token, doc.id);
      const approval = await api.getDocumentApproval(token, doc.id);
      const reqId = (approval as Record<string, unknown>)?.request_id as string;
      expect(reqId, "the approval request of the document").toBeTruthy();

      const rejected = await api.rejectRequest(token, reqId, {
        notes: "E2E rejection test",
      });
      expect(rejected).toBeTruthy();
      expect(rejected.status).toBe("REJECTED");
    } finally {
      await api.cancelDocument(token, doc.id).catch(() => {});
    }
    await api.deleteDocument(token, doc.id).catch(() => {});
  });
});

test.describe("Approvals — workflow lifecycle via API", () => {
  // Both children call org-wide approval cleanup in beforeAll and then
  // create a fresh workflow for the same target type — run them in one
  // serial worker so one child's cleanup cannot delete the other's
  // freshly created workflow mid-test (fullyParallel splits describes
  // across workers, and the two beforeAlls raced exactly that way).
  test.describe.configure({ mode: "serial" });

  test.describe("Approvals — multi-stage workflow", () => {
    test.describe.configure({ mode: "serial" });

    let api: ApiHelper;
    let token: string;
    let workflowId: string;
    let docId: string;
    let requestId: string;
    let storageId: string;

    test.beforeAll(async ({ playwright, baseURL }) => {
      const requestContext = await playwright.request.newContext({ baseURL });
      api = new ApiHelper(requestContext);
      const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
      token = authData.access_token;

      await api.toggleModule(token, "approvals", true).catch(() => {});
      await api.toggleModule(token, "warehouse", true).catch(() => {});
      // Its own location: the first one of the shared tenant belongs to
      // whichever parallel spec deletes it first.
      storageId = (
        await api.createStorage(token, {
          name: `E2E-Approvals-MultiStage-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        })
      ).id;

      await api.cleanupApprovals(token);

      try {
        const wf = await api.createWorkflow(token, {
          target_type: "document",
          is_active: true,
          name: `E2E-MultiStage-${Date.now()}`,
          stages: [
            {
              order: 1,
              label: "Manager Review",
              role: "manager",
              approver_user_ids: [],
            },
            {
              order: 2,
              label: "Director Approval",
              role: "director",
              approver_user_ids: [],
            },
          ],
        });
        workflowId = wf.id;
      } catch {
        // workflow creation may fail if stale requests block the target_type
      }
    });

    test.afterAll(async () => {
      if (token && docId) {
        await api.cancelDocument(token, docId).catch(() => {});
        await api.deleteDocument(token, docId).catch(() => {});
      }
      if (token && workflowId) {
        await api.deleteWorkflow(token, workflowId).catch(() => {});
      }
      if (token && storageId) {
        await api.deleteStorage(token, storageId).catch(() => {});
      }
    });

    test("creates 2-stage workflow", async () => {
      expect(workflowId, "the workflow the setup created").toBeTruthy();
      // stages may not be immediately visible — poll briefly
      let stages: Array<Record<string, unknown>> = [];
      for (let i = 0; i < 5; i++) {
        const wf = await api.getWorkflow(token, workflowId);
        stages =
          ((wf as Record<string, unknown>).stages as Array<
            Record<string, unknown>
          >) || [];
        if (stages.length === 2) break;
        await new Promise((r) => setTimeout(r, 500));
      }
      expect(stages.length).toBe(2);
    });

    test("creates document and requests approval", async () => {
      const doc = await api.createIntDocumentWithStock(token, {
        source_location_id: storageId,
        target_location_id: storageId,
        lines: [{ name: "E2E-MultiStage-Item", expected_quantity: 1 }],
      });
      docId = doc.id;

      await api.confirmDocument(token, docId);

      await api.requestDocumentApproval(token, docId);
      const approval = await api.getDocumentApproval(token, docId);
      requestId = (approval as Record<string, unknown>)?.request_id as string;
      expect(requestId, "the approval request of the document").toBeTruthy();
    });

    test("verifies approval is pending at stage 1", async () => {
      expect(requestId, "the approval request of the document").toBeTruthy();
      const req = await api.getRequest(token, requestId);
      expect(req.current_stage).toBe(1);
      expect(req.total_stages).toBe(2);
      expect(req.status).toBe("PENDING");
    });

    test("approves stage 1 — status stays PENDING (stage 2)", async () => {
      expect(requestId, "the approval request of the document").toBeTruthy();
      await api.approveRequest(token, requestId, {
        notes: "Stage 1 approved",
      });
      const req = await api.getRequest(token, requestId);
      expect(req.current_stage).toBe(2);
      expect(req.status).toBe("PENDING");
    });
  });

  test.describe("Approvals — workflow update", () => {
    test.describe.configure({ mode: "serial" });

    let api: ApiHelper;
    let token: string;
    let workflowId: string;

    test.beforeAll(async ({ playwright, baseURL }) => {
      const requestContext = await playwright.request.newContext({ baseURL });
      api = new ApiHelper(requestContext);
      const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
      token = authData.access_token;

      await api.toggleModule(token, "approvals", true).catch(() => {});

      await api.cleanupApprovals(token);

      try {
        const wf = await api.createWorkflow(token, {
          target_type: "document",
          is_active: true,
          name: `E2E-Update-${Date.now()}`,
          stages: [
            {
              order: 1,
              label: "Initial Review",
              role: "manager",
              approver_user_ids: [],
            },
          ],
        });
        workflowId = wf.id;
      } catch {
        // workflow creation may fail if stale requests block the target_type
      }
    });

    test.afterAll(async () => {
      if (token && workflowId) {
        await api.deleteWorkflow(token, workflowId).catch(() => {});
      }
    });

    test("updates workflow name via API", async () => {
      expect(workflowId, "the workflow the setup created").toBeTruthy();
      const updated = await api.updateWorkflow(token, workflowId, {
        name: "E2E-Updated-Workflow",
      });
      expect(updated).toBeTruthy();
    });

    test("verifies updated workflow via get", async () => {
      expect(workflowId, "the workflow the setup created").toBeTruthy();
      const wf = await api.getWorkflow(token, workflowId);
      expect(wf.name).toBe("E2E-Updated-Workflow");
    });

    test("workflows page loads after update", async ({
      page,
      authenticatedPage,
    }) => {
      await page.goto("/approvals/workflows");
      await page
        .waitForLoadState("networkidle", { timeout: 15000 })
        .catch(() => {});
      await expect(page.locator("h1, h2").first()).toBeVisible({
        timeout: 15000,
      });
    });
  });
});

test.describe("Approvals — request filtering", () => {
  test.describe.configure({ mode: "serial" });

  let api: ApiHelper;
  let token: string;

  test.beforeAll(async ({ playwright, baseURL }) => {
    const requestContext = await playwright.request.newContext({ baseURL });
    api = new ApiHelper(requestContext);
    const authData = await api.login(ADMIN_EMAIL, ADMIN_PASSWORD);
    token = authData.access_token;

    await api.toggleModule(token, "approvals", true).catch(() => {});
  });

  test("lists approval requests", async () => {
    const requests = await api.listRequests(token);
    expect(Array.isArray(requests)).toBe(true);
  });

  test("filters requests by target_type", async () => {
    const docRequests = await api.listRequests(token, "target_type=document");
    expect(Array.isArray(docRequests)).toBe(true);
  });

  test("filters requests by status", async () => {
    const pendingRequests = await api.listRequests(token, "status=PENDING");
    expect(Array.isArray(pendingRequests)).toBe(true);
  });

  test("approvals dashboard loads", async ({ page, authenticatedPage }) => {
    await page.goto("/approvals");
    await page
      .waitForLoadState("networkidle", { timeout: 15000 })
      .catch(() => {});
    await expect(page.locator("h1, h2").first()).toBeVisible({
      timeout: 15000,
    });
  });
});
