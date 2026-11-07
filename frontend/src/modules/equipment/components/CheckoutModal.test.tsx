/**
 * The checkout dialog's person field, against both registers a holder can
 * live in.
 *
 * A colleague with an account is offered from the directory; a hand-typed
 * address that matches nobody is named before the save — not discovered
 * later by a holder whose My Assets stays empty. The check never blocks:
 * equipment also goes to people no directory knows.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import userEvent from "@testing-library/user-event";
import { CheckoutModal } from "@/modules/equipment/components/CheckoutModal";
import { instantInsideDay } from "@/utils/zonedDay";
import type { Item } from "@/types";
import { onePage } from "@/test/mocks/page";

// The organization's clock for this file. The modal must send the return
// day inside *this* day — an instant in the browser's zone stored the next
// day for every organization east of the reader.
vi.mock("@/hooks/useOrganizationTimezone", () => ({
  useOrganizationTimezone: () => "Asia/Tokyo",
}));

// The real DateInput is a popover with its own calendar; the payload tests
// below only need to answer "which day was picked" and "what floor did the
// field advertise" (the same stub CreateCampaignModal.test.tsx uses).
vi.mock("@/components/ui/DateInput", () => ({
  DateInput: (props: {
    label: string;
    value: string;
    min?: string;
    onChange: (value: string) => void;
  }) => (
    <input
      aria-label={props.label}
      value={props.value}
      data-min={props.min}
      onChange={(e) => props.onChange(e.target.value)}
    />
  ),
}));

const makeItem = (): Item =>
  ({
    id: "item-1",
    location_id: "loc-1",
    category_id: null,
    name: "Laptop",
    brand: null,
    description: null,
    weight: null,
    quantity: 1,
    added_date: "2026-01-01",
    expiry_date: null,
    freeze_date: null,
    shelf_location: null,
    image_url: null,
    metadata: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  }) as unknown as Item;

const anna = {
  id: "u1",
  email: "anna@example.com",
  full_name: "Anna Nowak",
  role: "member",
};

function mockDirectories({
  members = [],
  partners = [],
}: {
  members?: Array<{
    id: string;
    email: string;
    full_name: string;
    role: string;
  }>;
  partners?: unknown[];
} = {}) {
  server.use(
    http.get("/api/v1/organizations/my/members", ({ request }) => {
      const search = new URL(request.url).searchParams.get("search") ?? "";
      const lower = search.toLowerCase();
      const items = members.filter(
        (m) =>
          m.email.toLowerCase().includes(lower) ||
          m.full_name.toLowerCase().includes(lower),
      );
      return HttpResponse.json({
        items,
        total: items.length,
        limit: 20,
        offset: 0,
      });
    }),
    http.get("/api/v1/partners", () =>
      HttpResponse.json({ items: partners, total: partners.length }),
    ),
    http.get("/api/v1/locations", () => HttpResponse.json(onePage([]))),
    http.get("/api/v1/locations*", () => HttpResponse.json([])),
    http.post("/api/v1/equipment/assignments", async ({ request }) => {
      postedCheckout = (await request.json()) as Record<string, unknown>;
      return HttpResponse.json({ id: "asg-1" }, { status: 201 });
    }),
  );
}

let postedCheckout: Record<string, unknown> | null = null;

async function fillPersonFields(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
  email: string,
) {
  await user.type(await screen.findByLabelText(/assigned to \(name\)/i), name);
  await user.type(screen.getByLabelText(/assigned to \(email\)/i), email);
}

describe("CheckoutModal — the person behind the address", () => {
  beforeEach(() => {
    postedCheckout = null;
  });

  it("warns before the save when the address matches nobody", async () => {
    mockDirectories({ members: [anna] });
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    await fillPersonFields(user, "Caspar Ghost", "ghost@example.com");

    expect(
      await screen.findByText(/no one in this organization uses this address/i),
    ).toBeInTheDocument();
  });

  it("announces the unmatched-address warning and ties it to the email field", async () => {
    // A warning a screen reader cannot hear is a warning only for the seeing.
    // The message carries a role, the field points at it, and the field is
    // marked invalid — the same contract `Input`'s own error slot follows.
    mockDirectories({ members: [anna] });
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    await fillPersonFields(user, "Caspar Ghost", "ghost@example.com");

    const warning = await screen.findByText(
      /no one in this organization uses this address/i,
    );
    expect(warning).toHaveAttribute("role", "alert");
    expect(warning.id).not.toBe("");
    const email = screen.getByLabelText(/assigned to \(email\)/i);
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(
      (email.getAttribute("aria-describedby") ?? "").split(/\s+/),
    ).toContain(warning.id);
  });

  it("keeps the email field linked to the consequence hint while no warning stands", () => {
    mockDirectories({ members: [anna] });
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    const hint = screen.getByText(
      /without an address the asset will not show up/i,
    );
    expect(hint.id).not.toBe("");
    const email = screen.getByLabelText(/assigned to \(email\)/i);
    expect(email).not.toHaveAttribute("aria-invalid");
    expect(
      (email.getAttribute("aria-describedby") ?? "").split(/\s+/),
    ).toContain(hint.id);
  });

  it("stays quiet when the address belongs to a member", async () => {
    mockDirectories({ members: [anna] });
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    await fillPersonFields(user, "Anna Nowak", "anna@example.com");

    await waitFor(() => {
      expect(
        screen.queryByText(/no one in this organization uses this address/i),
      ).not.toBeInTheDocument();
    });
    // The standing consequence sentence keeps its place.
    expect(
      screen.getByText(/without an address the asset will not show up/i),
    ).toBeInTheDocument();
  });

  it("stays quiet when the address belongs to a partner without an account", async () => {
    // The Partners register is the other half of the directory: contractors
    // and interns hold equipment without ever having an account, and the
    // warning must not accuse an address the employee book knows.
    mockDirectories({
      members: [],
      partners: [
        {
          id: "partner-1",
          name: "Bartosz Kowalski",
          email: "bartosz@example.org",
          contact_person: null,
        },
      ],
    });
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    await fillPersonFields(user, "Bartosz Kowalski", "bartosz@example.org");

    expect(
      screen.queryByText(/no one in this organization uses this address/i),
    ).not.toBeInTheDocument();
  });

  it("still checks the asset out to an address nobody knows", async () => {
    mockDirectories({ members: [anna] });
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    await fillPersonFields(user, "Tomasz Praktykant", "tomasz@szkola.edu");
    // The warning stands; the reader has seen it, and one click saves.
    await screen.findByText(/no one in this organization uses this address/i);
    await user.click(screen.getByRole("button", { name: /check out/i }));

    await waitFor(() => {
      expect(postedCheckout).not.toBeNull();
    });
    expect(postedCheckout?.assigned_to_email).toBe("tomasz@szkola.edu");
    expect(postedCheckout?.assigned_to_name).toBe("Tomasz Praktykant");
  });

  /**
   * The warning has no blind window. It is highlighted once the typing has
   * settled for 400 ms, and the save used not to wait for it: an address
   * pasted and submitted inside the window was stored with no warning ever
   * on screen. Here the address lands and the form is submitted in the same
   * tick, so no timer can settle in between. Measured with the save not
   * waiting for the check: only this test goes red, the first submit
   * having posted the checkout (`expected { item_id: 'item-1', …(2) } to
   * be null`).
   */
  it("names an address submitted inside the settle window before saving it", async () => {
    mockDirectories({ members: [anna] });
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<CheckoutModal item={makeItem()} onClose={onClose} />);
    await user.type(
      await screen.findByLabelText(/assigned to \(name\)/i),
      "Caspar Ghost",
    );
    const submit = screen.getByRole("button", { name: /check out/i });

    fireEvent.change(screen.getByLabelText(/assigned to \(email\)/i), {
      target: { value: "ghost@example.com" },
    });
    fireEvent.click(submit);

    expect(
      await screen.findByText(/no one in this organization uses this address/i),
    ).toBeInTheDocument();
    expect(postedCheckout).toBeNull();
    expect(onClose).not.toHaveBeenCalled();

    // The warning seen, the next submit saves the address as typed.
    await user.click(submit);
    await waitFor(() => expect(postedCheckout).not.toBeNull());
    expect(postedCheckout?.assigned_to_email).toBe("ghost@example.com");
  });

  /** Pin, passes either way: a known address costs no second submit. */
  it("saves a known address submitted at once, in one step", async () => {
    mockDirectories({ members: [anna] });
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);
    await user.type(
      await screen.findByLabelText(/assigned to \(name\)/i),
      "Anna Nowak",
    );

    fireEvent.change(screen.getByLabelText(/assigned to \(email\)/i), {
      target: { value: "anna@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /check out/i }));

    await waitFor(() => expect(postedCheckout).not.toBeNull());
    expect(postedCheckout?.assigned_to_email).toBe("anna@example.com");
    expect(
      screen.queryByText(/no one in this organization uses this address/i),
    ).not.toBeInTheDocument();
  });

  it("fills the fields when a member is picked from the directory", async () => {
    mockDirectories({ members: [anna] });
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    const search = await screen.findByLabelText(/^person$/i);
    await user.type(search, "anna");
    await user.click(await screen.findByText("Anna Nowak"));

    expect(screen.getByLabelText(/assigned to \(name\)/i)).toHaveValue(
      "Anna Nowak",
    );
    expect(screen.getByLabelText(/assigned to \(email\)/i)).toHaveValue(
      "anna@example.com",
    );
  });
});

describe("CheckoutModal — the return day travels on the organization's clock", () => {
  // Any day comfortably in the future, so the past-date refusal stays quiet.
  const pickedDay = `${new Date().getFullYear() + 1}-09-30`;

  beforeEach(() => {
    postedCheckout = null;
  });

  it("sends noon of the picked day in the organization's zone, not UTC midnight", async () => {
    mockDirectories({ members: [] });
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    fireEvent.change(await screen.findByLabelText(/assigned to \(name\)/i), {
      target: { value: "Tomasz Praktykant" },
    });
    fireEvent.change(screen.getByLabelText(/expected return/i), {
      target: { value: pickedDay },
    });
    fireEvent.click(screen.getByRole("button", { name: /check out/i }));

    await waitFor(() => expect(postedCheckout).not.toBeNull());
    // Noon in the org's zone, not the picked day at UTC midnight: the
    // backend reads the arrival through the org clock, so the day it sees
    // there is the day the form said.
    expect(postedCheckout?.expected_return_at).toBe(
      instantInsideDay(pickedDay, "Asia/Tokyo").toISOString(),
    );
  });

  it("floors the calendar on the organization's today, not the reader's", () => {
    // 16:00 UTC is the 23rd in the reader's zone and already the 24th in
    // Tokyo: the org's day, not the browser's, is the one that has finished.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-23T16:00:00Z"));
    try {
      mockDirectories({ members: [] });
      render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

      fireEvent.change(screen.getByLabelText(/expected return/i), {
        target: { value: "2026-09-23" },
      });

      expect(screen.getByRole("alert")).toHaveTextContent(
        /cannot be in the past/i,
      );
    } finally {
      vi.useRealTimers();
    }
  });
});

/**
 * A checkout can put an asset in a place instead of a person's hands. The
 * failures caught: the location-mode request still carrying a person (or
 * no location), a checkout sent with a return day already past, and a
 * finished checkout that leaves the dialog open or skips the caller's
 * follow-up (the protocol offer hangs off it).
 */
describe("CheckoutModal — to a location, and the return date", () => {
  it("places the asset in the chosen location with the notes, then hands over and closes", async () => {
    mockDirectories();
    server.use(
      http.get("/api/v1/locations", () =>
        HttpResponse.json(
          onePage([{ id: "loc-7", name: "Meeting room", items_count: 0 }]),
        ),
      ),
    );
    const onClose = vi.fn();
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(
      <CheckoutModal item={makeItem()} onClose={onClose} onDone={onDone} />,
    );

    await user.click(screen.getByRole("button", { name: "To Location" }));
    const submit = screen.getByRole("button", { name: "Check Out" });
    expect(submit).toBeDisabled();

    fireEvent.click(await screen.findByRole("combobox", { name: "Location" }));
    fireEvent.click(await screen.findByText("Meeting room"));
    await user.type(screen.getByLabelText("Notes"), "For the board meeting");
    await user.click(submit);

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(postedCheckout).toMatchObject({
      item_id: "item-1",
      assigned_to_name: "",
      checkout_location_id: "loc-7",
      checkout_notes: "For the board meeting",
    });
    expect(postedCheckout?.assigned_to_email).toBeUndefined();
    expect(onDone).toHaveBeenCalledWith({ id: "asg-1" });
  });

  it("refuses a return day in the organization's past, before anything is sent", async () => {
    mockDirectories();
    postedCheckout = null;
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    await fillPersonFields(user, "Anna Nowak", "anna@example.com");
    fireEvent.change(screen.getByLabelText("Expected Return Date"), {
      target: { value: "2000-01-01" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The return date cannot be in the past.",
    );
    await user.click(screen.getByRole("button", { name: "Check Out" }));
    expect(postedCheckout).toBeNull();
  });

  it("opens the quick location form from the picker", async () => {
    mockDirectories();
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "To Location" }));
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(
      await screen.findByRole("dialog", { name: "Add Location" }),
    ).toBeInTheDocument();
  });
});

/**
 * Under an approval workflow a checkout can be refused for want of an
 * approval. The dialog used to answer with a toast and nothing else: the
 * reader closed it, asked on the page, waited, and typed the holder again.
 * And the request carried no holder, so the approver decided blind.
 */
describe("CheckoutModal — asking for the approval of this checkout", () => {
  let posted: Record<string, unknown> | null;

  beforeEach(() => {
    posted = null;
    postedCheckout = null;
    // A colleague the directory knows: the address warning is not what
    // these tests are about.
    mockDirectories({
      members: [
        {
          id: "u2",
          email: "kasia@example.com",
          full_name: "Kasia Kowalska",
          role: "member",
        },
      ],
    });
    server.use(
      http.post("/api/v1/equipment/item-1/request-approval", async (req) => {
        posted = (await req.request.json()) as Record<string, unknown>;
        return HttpResponse.json({ request_id: "r-1", status: "PENDING" });
      }),
    );
  });

  it("offers the request where the refusal is shown, with the holder typed", async () => {
    server.use(
      http.post("/api/v1/equipment/assignments", () =>
        HttpResponse.json(
          {
            detail: {
              code: "APPROVAL_REQUIRED",
              message:
                "This action needs an approval first. Request one before continuing.",
            },
          },
          { status: 409 },
        ),
      ),
    );
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={onClose} />);

    await fillPersonFields(user, "Kasia Kowalska", "kasia@example.com");
    await user.click(screen.getByRole("button", { name: "Check Out" }));

    const ask = await screen.findByRole("button", {
      name: "Request approval for this checkout",
    });
    expect(onClose).not.toHaveBeenCalled();
    // Structure only (jsdom has no layout): the refusal is outside the
    // scrolling form, so on a phone it cannot land below the fold while the
    // footer's button stays in view.
    expect(screen.getByTestId("checkout-modal-body")).not.toContainElement(
      screen.getByRole("alert"),
    );
    await user.click(ask);

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted?.assigned_to_name).toBe("Kasia Kowalska");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("asks for the approval of the checkout it describes", async () => {
    const user = userEvent.setup();
    render(
      <CheckoutModal item={makeItem()} purpose="request" onClose={vi.fn()} />,
    );

    expect(
      screen.getByRole("heading", { name: "Request approval for a checkout" }),
    ).toBeInTheDocument();
    await fillPersonFields(user, "Kasia Kowalska", "kasia@example.com");
    fireEvent.change(screen.getByLabelText("Expected Return Date"), {
      target: { value: "2099-11-05" },
    });
    await user.click(screen.getByRole("button", { name: "Send for approval" }));

    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted?.assigned_to_name).toBe("Kasia Kowalska");
    expect(posted?.expected_return_at).toBe(
      instantInsideDay("2099-11-05", "Asia/Tokyo").toISOString(),
    );
    // Nothing was checked out: the request is all this dialog sent.
    expect(postedCheckout).toBeNull();
  });
});

/**
 * A checkout the server refuses for a reason of its own (an address on a
 * reserved domain, say) used to be answered by a toast alone: it rises at the
 * edge of the screen, outside the dialog the reader is looking at, and is gone
 * in seconds — the fields stay filled, the button stays active, and the dialog
 * itself says nothing. The refusal belongs where the click was.
 */
describe("CheckoutModal — a refusal is read in the dialog", () => {
  const refuse = () =>
    server.use(
      http.post("/api/v1/equipment/assignments", () =>
        HttpResponse.json(
          {
            detail: [
              {
                type: "value_error",
                loc: ["body", "assigned_to_email"],
                msg: "That address is on a reserved domain.",
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );

  beforeEach(() => {
    postedCheckout = null;
    mockDirectories({ members: [] });
  });

  it("shows the reason in the dialog, outside the scrolling form, and keeps the fields", async () => {
    refuse();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={onClose} />);

    await fillPersonFields(user, "Jan Test", "jan@foo.invalid");
    // Nobody's address: the reader sees the warning, then saves anyway.
    await screen.findByText(/no one in this organization uses this address/i);
    await user.click(screen.getByRole("button", { name: "Check Out" }));

    const reason = await screen.findByText(
      "That address is on a reserved domain.",
    );
    expect(reason).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("checkout-modal-body")).not.toContainElement(
      reason,
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/assigned to \(email\)/i)).toHaveValue(
      "jan@foo.invalid",
    );
  });

  it("clears the reason when the reader tries again", async () => {
    refuse();
    const user = userEvent.setup();
    render(<CheckoutModal item={makeItem()} onClose={vi.fn()} />);

    await fillPersonFields(user, "Jan Test", "jan@foo.invalid");
    // Nobody's address: the reader sees the warning, then saves anyway.
    await screen.findByText(/no one in this organization uses this address/i);
    await user.click(screen.getByRole("button", { name: "Check Out" }));
    await screen.findByText("That address is on a reserved domain.");

    server.use(
      http.post("/api/v1/equipment/assignments", () =>
        HttpResponse.json({ id: "asg-1" }, { status: 201 }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "Check Out" }));

    await waitFor(() =>
      expect(
        screen.queryByText("That address is on a reserved domain."),
      ).not.toBeInTheDocument(),
    );
  });
});
