/**
 * The batch "Assign to Person" dialog, against both registers a holder can
 * live in.
 *
 * It used to search the Partners register only — a colleague with an
 * account was answered with "add records in the Partners module" — and it
 * sent only a partner_id, so a batch-issued asset never carried the email
 * "My assets" matches on, and the person holding it could not see it.
 */
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import userEvent from "@testing-library/user-event";
import { BulkEditDialogs } from "@/modules/equipment/components/BulkEditDialogs";

const anna = {
  id: "u1",
  email: "anna@example.com",
  full_name: "Anna Nowak",
  role: "member",
};

function mockDirectories(members: object[]) {
  server.use(
    http.get("/api/v1/organizations/my/members", () =>
      HttpResponse.json({
        items: members,
        total: members.length,
        limit: 20,
        offset: 0,
      }),
    ),
    http.get("/api/v1/partners", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
  );
}

describe("BulkEditDialogs — assign to person", () => {
  it("offers organization accounts and sends the email that connects the asset", async () => {
    mockDirectories([anna]);
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <BulkEditDialogs
        action="assign_to"
        selectedCount={3}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
        isPending={false}
      />,
    );

    const search = await screen.findByPlaceholderText(/search people/i);
    await user.type(search, "anna");
    await user.click(await screen.findByText("Anna Nowak"));
    await user.click(screen.getByRole("button", { name: /apply/i }));

    expect(onConfirm).toHaveBeenCalledWith("assign_to", {
      partner_id: null,
      assigned_to_name: "Anna Nowak",
      assigned_to_email: "anna@example.com",
    });
  });

  it("warns when the picked person has no email on record", async () => {
    // A partner without an address is issuable, but "My assets" matches
    // the holder by email — the batch would hand things to someone who
    // can never see them. The single checkout warns about this; the bulk
    // dialog said nothing.
    server.use(
      http.get("/api/v1/organizations/my/members", () =>
        HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 }),
      ),
      http.get("/api/v1/partners", () =>
        HttpResponse.json({
          items: [{ id: "p1", name: "Marek Cichy", email: null }],
          total: 1,
        }),
      ),
    );
    const user = userEvent.setup();
    render(
      <BulkEditDialogs
        action="assign_to"
        selectedCount={3}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isPending={false}
      />,
    );

    const search = await screen.findByPlaceholderText(/search people/i);
    await user.type(search, "marek");
    await user.click(await screen.findByText("Marek Cichy"));

    expect(screen.getByText(/no email on record/i)).toBeInTheDocument();
  });

  it("stays quiet about the address when the pick carries one", async () => {
    mockDirectories([anna]);
    const user = userEvent.setup();
    render(
      <BulkEditDialogs
        action="assign_to"
        selectedCount={3}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
        isPending={false}
      />,
    );

    const search = await screen.findByPlaceholderText(/search people/i);
    await user.type(search, "anna");
    await user.click(await screen.findByText("Anna Nowak"));

    expect(screen.queryByText(/no email on record/i)).not.toBeInTheDocument();
  });

  it("stays on an empty directory instead of sending a bare partner id", async () => {
    mockDirectories([]);
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(
      <BulkEditDialogs
        action="assign_to"
        selectedCount={3}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
        isPending={false}
      />,
    );

    const search = await screen.findByPlaceholderText(/search people/i);
    await user.type(search, "nobody");

    // Nothing picked → nothing applied. The old dialog enabled its Apply
    // only for partner picks and sent "" for everyone else.
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /apply/i })).toBeDisabled();
  });
});
