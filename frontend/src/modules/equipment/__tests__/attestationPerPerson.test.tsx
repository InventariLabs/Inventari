/**
 * regression: one attestation response per person.
 *
 * The public page lists every asset under one token, confirms all of them
 * at once, and the dispute form names a specific asset when there are
 * several.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@/test/utils";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import AttestationPublicPage from "@/modules/equipment/pages/AttestationPublicPage";
import { DisputeForm } from "@/modules/equipment/components/attestation/DisputeForm";

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useParams: () => ({ token: "tok-1" }),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

const multiItemResponse = {
  id: "resp-1",
  campaign_id: "camp-1",
  assignment_id: null,
  assignee_email: "anna@example.com",
  assignee_name: "Anna Kowalska",
  item_name: "Laptop A",
  serial_number: "SN-A",
  items: [
    {
      id: "item-1",
      response_id: "resp-1",
      assignment_id: "asg-1",
      item_id: "it-1",
      item_name: "Laptop A",
      serial_number: "SN-A",
      status: "PENDING" as const,
      dispute_type: null,
      dispute_reason: null,
      returned: false,
    },
    {
      id: "item-2",
      response_id: "resp-1",
      assignment_id: "asg-2",
      item_id: "it-2",
      item_name: "Monitor B",
      serial_number: null,
      status: "PENDING" as const,
      dispute_type: null,
      dispute_reason: null,
      returned: false,
    },
  ],
  status: "PENDING",
  responded_at: null,
  dispute_reason: null,
  dispute_type: null,
  email_sent_at: null,
  reminder_sent_at: null,
  created_at: "2026-08-01T00:00:00Z",
};

describe(" per-person attestation", () => {
  it("lists every asset under one token", async () => {
    window.history.pushState({}, "", "/public/attestation/tok-1");
    server.use(
      http.get("/public/attestation/tok-1", () =>
        HttpResponse.json(multiItemResponse),
      ),
    );

    render(<AttestationPublicPage />);

    await waitFor(() => {
      expect(screen.getByText("Laptop A")).toBeInTheDocument();
    });
    expect(screen.getByText("Monitor B")).toBeInTheDocument();
  });

  it("dispute form selects one asset when there are several", async () => {
    const onSubmit = vi.fn();
    render(
      <DisputeForm
        items={multiItemResponse.items}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
        isPending={false}
      />,
    );

    // No asset selected yet → submit disabled.
    const submit = screen.getByRole("button", { name: /submit report/i });
    expect(submit).toBeDisabled();

    // Pick "Monitor B" in the asset selector (Radix Select) — the trigger
    // sits right under the "Select the asset" label.
    const selectLabel = screen.getByText("Select the asset");
    const trigger = selectLabel.parentElement?.querySelector(
      "button",
    ) as HTMLButtonElement;
    fireEvent.click(trigger);
    await waitFor(() => {
      expect(
        screen.getByRole("option", { name: "Monitor B" }),
      ).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("option", { name: "Monitor B" }));

    // The issue type starts unselected: it is a choice, not a default.
    fireEvent.click(screen.getByRole("combobox", { name: /issue type/i }));
    fireEvent.click(await screen.findByRole("option", { name: /^Missing/ }));

    fireEvent.change(
      screen.getByPlaceholderText("Please describe the issue in detail…"),
      { target: { value: "Screen cracked" } },
    );
    fireEvent.click(submit);

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        "MISSING",
        "Screen cracked",
        "asg-2",
      );
    });
  });
});
