import { test, expect } from "./fixtures/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD } from "./fixtures/credentials";
import { ApiHelper } from "./helpers/api";
import { defineStepTask, type StepEnv } from "./helpers/core-task";
import { showMoreUntilVisible } from "./helpers/todo-list";

/**
 * The approval of a document, counted as a core task.
 *
 * Kept in its own file because it needs an approval workflow, and a workflow
 * applies to every document of the organisation: the file's name puts it in
 * the one-worker `approvals` project, which runs once the other projects are
 * done. The workflow it creates is removed again when the file is finished.
 */

/** Clears what an earlier spec left, then raises the one workflow the walk needs. */
async function oneStageWorkflow(env: StepEnv) {
  await env.api.toggleModule(env.token, "approvals", true).catch(() => {});
  // A single user raises the request and decides it here.
  await env.api.setModuleSettings(env.token, "approvals", {
    allow_admin_self_approve: true,
  });
  await env.api.cleanupApprovals(env.token);
  for (const workflow of await env.api.listWorkflows(env.token)) {
    if (workflow.target_type === "document") {
      await env.api.deleteWorkflow(env.token, workflow.id).catch(() => {});
    }
  }
  await env.api.createWorkflow(env.token, {
    target_type: "document",
    is_active: true,
    name: `E2E-Steps-Approve-${env.uid}`,
    stages: [
      { order: 1, label: "Review", role: "manager", approver_user_ids: [] },
    ],
  });
}

test.afterAll(async ({ playwright, baseURL }) => {
  const ctx = await playwright.request.newContext({ baseURL });
  const api = new ApiHelper(ctx);
  const token = (await api.login(ADMIN_EMAIL, ADMIN_PASSWORD)).access_token;
  await api.cleanupApprovals(token);
  for (const workflow of await api.listWorkflows(token)) {
    if (workflow.name.startsWith("E2E-Steps-Approve-")) {
      await api.deleteWorkflow(token, workflow.id).catch(() => {});
    }
  }
  await api
    .setModuleSettings(token, "approvals", { allow_admin_self_approve: false })
    .catch(() => {});
  await ctx.dispose();
});

defineStepTask({
  task: "approve-a-document",
  title: "approve a document that waits for a decision",
  start: "/warehouse/todo",
  async seed(env) {
    await oneStageWorkflow(env);
    const from = await env.api.createStorageIdempotent(env.token, {
      name: `E2E-Steps-Approve-From-${env.uid}`,
      location_type: "SHELF",
    });
    const to = await env.api.createStorageIdempotent(env.token, {
      name: `E2E-Steps-Approve-To-${env.uid}`,
      location_type: "SHELF",
    });
    const draft = await env.api.createIntDocumentWithStock(env.token, {
      source_location_id: from.id,
      target_location_id: to.id,
      lines: [
        { name: `E2E-Steps-Approve-Goods-${env.uid}`, expected_quantity: 2 },
      ],
    });
    // With the workflow in place, confirming is what sends it for a decision.
    await env.api.confirmDocument(env.token, draft.id);
    const waiting = await env.api.getDocument(env.token, draft.id);
    return { documentId: draft.id, number: String(waiting.number) };
  },
  async walk(page, seed, _viewport, steps) {
    // Start lists the document as a task with Review approval; the document's
    // page has Approve, which asks once more before it decides.
    // The shared database holds more than a hundred older tasks; asking for
    // the rest of the list is the database's doing, not a step of the task.
    await steps.uncounted(() =>
      showMoreUntilVisible(page, page.getByText(`Approve ${seed.number}`)),
    );
    await page
      .locator("div")
      .filter({ hasText: `Approve ${seed.number}` })
      .filter({ has: page.getByRole("button", { name: "Review approval" }) })
      .last()
      .getByRole("button", { name: "Review approval" })
      .click();
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await page
      .getByRole("alertdialog", { name: `Approve ${seed.number}?` })
      .getByRole("button", { name: "Approve request" })
      .click();
    await expect(page.getByRole("alertdialog")).toBeHidden();
  },
  async verify(env, seed) {
    await expect
      .poll(async () => {
        const approval = (await env.api.getDocumentApproval(
          env.token,
          seed.documentId,
        )) as Record<string, unknown> | null;
        return approval?.status;
      })
      .toBe("APPROVED");
  },
});
