import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CreateCampaignModal } from "./CreateCampaignModal";
import { instantInsideDay } from "@/utils/zonedDay";
import type { Organization } from "@/types";

/**
 * An attestation is a request that travels by mail. On an installation that
 * sends no mail the dialog used to offer subject lines and reminders as if
 * something would go out — the invitations screen already reads
 * `can_send_email` and says so; the campaign dialog now does the same.
 */

const organization: { can_send_email?: boolean; timezone?: string } = {};

const createMutate = vi.fn();

vi.mock("@/modules/settings/hooks/useOrganization", () => ({
  useShowModuleData: () => true,
  useOrganization: () => ({
    data: organization as Organization | undefined,
  }),
}));

vi.mock("@/modules/equipment/hooks/useEquipment", () => ({
  useCreateCampaign: () => ({ mutate: createMutate, isPending: false }),
  useScopePreview: () => ({ data: undefined }),
}));

// The real DateInput is a popover with its own calendar; the payload tests
// below only need to answer "which day was picked" and "what floor did the
// field advertise".
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

vi.mock("@/lib/api/categories", () => ({
  categoriesApi: { getAll: vi.fn().mockResolvedValue([]) },
}));

function renderModal() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>
        <CreateCampaignModal onClose={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CreateCampaignModal — an installation without mail says so", () => {
  beforeEach(() => {
    organization.can_send_email = undefined;
  });

  it("warns before creation that nothing will go out by itself", () => {
    organization.can_send_email = false;
    renderModal();

    expect(screen.getByText(/does not send email/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Set up email" })).toHaveAttribute(
      "href",
      "/settings/email",
    );
  });

  it("promises no sending above the warning that nothing is sent", () => {
    organization.can_send_email = false;
    renderModal();

    expect(
      screen.getByText("Assignees in scope confirm the assets they hold."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Send an attestation/)).not.toBeInTheDocument();
  });

  it("stays quiet on an installation that sends mail", () => {
    organization.can_send_email = true;
    renderModal();

    expect(screen.queryByText(/does not send email/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Custom Email Subject/i)).toBeInTheDocument();
    expect(
      screen.getByText("Assignees in scope confirm the assets they hold."),
    ).toBeInTheDocument();
  });
});

describe("CreateCampaignModal — the day travels on the org's clock", () => {
  beforeEach(() => {
    createMutate.mockClear();
    organization.can_send_email = true;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("sends noon of the picked day in the organization's zone", async () => {
    // The write half of the org-clock contract: the backend reads the
    // arrival through the org's clock, so the form owes an instant inside
    // the org's day — not an instant in the browser's zone, which stored
    // the next day for every org east of the reader.
    organization.timezone = "Asia/Tokyo";
    renderModal();

    fireEvent.change(screen.getByLabelText("Deadline"), {
      target: { value: "2026-09-23" },
    });
    fireEvent.change(screen.getByLabelText(/Attestation name/i), {
      target: { value: "Q3 audit" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Create attestation/i }),
    );

    expect(createMutate).toHaveBeenCalledTimes(1);
    const payload = createMutate.mock.calls[0]![0] as { deadline: string };
    expect(payload.deadline).toBe(
      instantInsideDay("2026-09-23", "Asia/Tokyo").toISOString(),
    );
    expect(payload.deadline).toBe("2026-09-23T03:00:00.000Z");
  });

  it("floors the calendar on the organization's today, not the reader's", () => {
    // 16:00 UTC is the 23rd in UTC and already the 24th in Tokyo: a floor
    // computed on the reader's clock offered Tokyo a day it had finished.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-23T16:00:00Z"));
    organization.timezone = "Asia/Tokyo";
    renderModal();

    expect(screen.getByLabelText("Deadline")).toHaveAttribute(
      "data-min",
      "2026-09-24",
    );
  });
});

/**
 * A scope covers the assets somebody holds — that is who can attest. The
 * control used to say "All assets", a set one word wider than the sentence
 * beneath it ("Every checked-out asset will be attested"): an organization
 * with nothing checked out read a promise of an inventory-wide attestation
 * and learned the truth only from the count line, if at all.
 */
describe("CreateCampaignModal — the scope names the set it covers", () => {
  it("names the checked-out set in the control and in the sentence alike", () => {
    renderModal();

    expect(screen.getByLabelText("Scope")).toHaveTextContent(/checked-out/i);
    expect(
      screen.getByText(/Every checked-out asset will be attested/),
    ).toBeInTheDocument();
  });
});

describe("CreateCampaignModal — a scope list that did not arrive", () => {
  it("says so, with a retry, instead of offering an empty storage picker", async () => {
    let asked = 0;
    server.use(
      http.get("/api/v1/locations", () => {
        asked += 1;
        return HttpResponse.json({ detail: "down" }, { status: 500 });
      }),
    );
    renderModal();

    fireEvent.click(screen.getByRole("combobox", { name: /Scope/ }));
    fireEvent.click(screen.getByRole("option", { name: "By location" }));
    fireEvent.click(
      await screen.findByRole("combobox", { name: /Select location/ }),
    );

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const before = asked;
    fireEvent.click(screen.getByRole("button", { name: /retry|try again/i }));
    await waitFor(() => expect(asked).toBeGreaterThan(before));
  });
});

/**
 * A narrowed attestation names the one category or location it covers,
 * and the optional fields travel with it. The failures caught: a category
 * scope sent without its id (the backend would ask the whole organization),
 * an optional field whose edit never reaches the request, and a narrowed
 * scope with no filter picked going out anyway.
 */
describe("CreateCampaignModal — a narrowed attestation and its options", () => {
  beforeEach(() => {
    createMutate.mockClear();
    organization.timezone = "UTC";
    organization.can_send_email = true;
  });

  async function chooseCategoryScope() {
    const { categoriesApi } = await import("@/lib/api/categories");
    vi.mocked(categoriesApi.getAll).mockResolvedValue([
      { id: "cat-lap", name: "Laptops", code: null },
    ] as never);
    renderModal();
    fireEvent.click(screen.getByRole("combobox", { name: /Scope/ }));
    fireEvent.click(screen.getByRole("option", { name: "By category" }));
  }

  function fillRequired() {
    fireEvent.change(screen.getByLabelText(/Attestation name/i), {
      target: { value: "  Laptop check  " },
    });
    fireEvent.change(screen.getByLabelText("Deadline"), {
      target: { value: "2026-12-01" },
    });
  }

  it("sends the chosen category with the description, reminder and subject", async () => {
    await chooseCategoryScope();
    fireEvent.click(
      await screen.findByRole("combobox", { name: /Select category/ }),
    );
    fireEvent.click(await screen.findByRole("option", { name: "Laptops" }));
    fillRequired();
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Yearly check" },
    });
    fireEvent.change(screen.getByLabelText(/Reminder/), {
      target: { value: "5" },
    });
    fireEvent.change(screen.getByLabelText("Custom Email Subject"), {
      target: { value: "Please confirm your laptop" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: /Create attestation/i }),
    );

    expect(createMutate).toHaveBeenCalledTimes(1);
    expect(createMutate.mock.calls[0]![0]).toMatchObject({
      name: "Laptop check",
      description: "Yearly check",
      reminder_days_before: 5,
      email_subject: "Please confirm your laptop",
      scope_type: "CATEGORY",
      scope_filter_id: "cat-lap",
    });
  });

  it("sends nothing while a narrowed scope has no category picked", async () => {
    await chooseCategoryScope();
    fillRequired();
    fireEvent.click(
      screen.getByRole("button", { name: /Create attestation/i }),
    );
    expect(createMutate).not.toHaveBeenCalled();
  });
});
