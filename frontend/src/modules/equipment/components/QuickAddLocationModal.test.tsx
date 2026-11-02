import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { QueryWrapper } from "@/test/queryWrapper";

import QuickAddLocationModal from "./QuickAddLocationModal";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

let created: Record<string, unknown> | null;

beforeEach(() => {
  created = null;
  server.use(
    http.get("/api/v1/locations", () =>
      HttpResponse.json(
        onePage([{ id: "loc-office", name: "Warsaw office", items_count: 0 }]),
      ),
    ),
    http.post("/api/v1/locations/hierarchy", async ({ request }) => {
      created = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ id: "loc-new", name: "Server room" });
    }),
  );
});

function renderModal() {
  const onClose = vi.fn();
  const onCreated = vi.fn();
  render(
    <QueryWrapper>
      <QuickAddLocationModal isOpen onClose={onClose} onCreated={onCreated} />
    </QueryWrapper>,
  );
  return { onClose, onCreated, user: userEvent.setup() };
}

/**
 * The quick form is how a checkout or an asset gets a place that did not
 * exist a moment ago. The failures caught: the new place created without
 * the module's tag or its parent, the caller never told which id to select,
 * and a refusal that closes the form with nothing said.
 */
describe("QuickAddLocationModal", () => {
  it("creates a tagged location under the chosen parent and hands its id back", async () => {
    const { onClose, onCreated, user } = renderModal();

    await user.type(screen.getByLabelText(/Location name/), " Server room ");
    await user.type(screen.getByLabelText("Description"), "Second floor");
    await user.click(
      await screen.findByRole("combobox", { name: "Parent location" }),
    );
    // The picker's panel opens as a second dialog over the form.
    const dialogs = await screen.findAllByRole("dialog");
    const panel = dialogs[dialogs.length - 1];
    await user.click(within(panel).getByText("Warsaw office"));
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("loc-new"));
    expect(created).toMatchObject({
      parent_id: "loc-office",
      steps: [{ name: "Server room" }],
      description: "Second floor",
      context_tag: "equipment",
    });
    expect(toast.success).toHaveBeenCalledWith("Location created successfully");
    expect(onClose).toHaveBeenCalled();
  });

  it("says why the location was refused and stays open", async () => {
    server.use(
      http.post("/api/v1/locations/hierarchy", () =>
        HttpResponse.json({ detail: "Name already in use" }, { status: 409 }),
      ),
    );
    const { onClose, onCreated, user } = renderModal();

    await user.type(screen.getByLabelText(/Location name/), "Server room");
    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Name already in use"),
    );
    expect(onCreated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("keeps Add off without a name, and Cancel closes without a request", async () => {
    const { onClose, user } = renderModal();

    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
    await user.click(screen.getByText("Cancel", { selector: "button" }));
    expect(onClose).toHaveBeenCalled();
    expect(created).toBeNull();
  });
});
