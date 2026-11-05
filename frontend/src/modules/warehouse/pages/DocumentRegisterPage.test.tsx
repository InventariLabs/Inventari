import React, { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@/test/utils";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import DocumentRegisterPage from "./DocumentRegisterPage";
import * as documentsHooks from "@/modules/warehouse/hooks/useDocuments";
import * as profileHooks from "@/modules/warehouse/hooks/useDocumentProfile";
import type {
  RegisterResponse,
  RegisterRowsResponse,
} from "@/modules/warehouse/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", async () => {
  const actual = await vi.importActual<
    typeof import("@/modules/warehouse/hooks/useDocuments")
  >("@/modules/warehouse/hooks/useDocuments");
  return {
    ...actual,
    useDocumentRegister: vi.fn(),
    useDocumentRegisterRows: vi.fn(),
  };
});

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", async () => {
  const actual = await vi.importActual<
    typeof import("@/modules/warehouse/hooks/useDocumentProfile")
  >("@/modules/warehouse/hooks/useDocumentProfile");
  return {
    ...actual,
    useDocumentProfile: vi.fn(),
  };
});

function HeaderHarness({ children }: { children: React.ReactNode }) {
  const [headerData, setHeaderData] = useState<PageHeaderData>({});

  return (
    <PageHeaderContext.Provider
      value={{ data: headerData, setHeader: setHeaderData }}
    >
      {children}
    </PageHeaderContext.Provider>
  );
}

function buildRegisterResponse(): RegisterResponse {
  return {
    date_from: "2026-04-01",
    date_to: "2026-04-30",
    group_by: "type",
    groups: [
      {
        key: "IN",
        label: "IN",
        document_count: 2,
        total_net: "60.00",
        total_tax: "13.80",
        total_gross: "73.80",
        currency: "USD",
        totals_by_currency: [
          {
            currency: "USD",
            total_net: "60.00",
            total_tax: "13.80",
            total_gross: "73.80",
          },
        ],
      },
    ],
    summary: {
      has_shipments: false,
      scrap_documents: 0,
      documents_without_value: 0,
      total_documents: 2,
      total_net: "60.00",
      total_tax: "13.80",
      total_gross: "73.80",
      currency: "USD",
      totals_by_currency: [
        {
          currency: "USD",
          total_net: "60.00",
          total_tax: "13.80",
          total_gross: "73.80",
        },
      ],
    },
  };
}

/** The rows page the IN group serves once it is opened. */
function buildRowsResponse(): RegisterRowsResponse {
  return {
    total: 2,
    limit: 50,
    offset: 0,
    has_more: false,
    total_capped: false,
    items: [
      {
        id: "doc-1",
        number: "IN/2026/001",
        type: "IN",
        status: "COMPLETED",
        date: "2026-04-05",
        partner_name: "Acme",
        source_location_name: null,
        target_location_name: "Main",
        total_net: "20.00",
        total_tax: "4.60",
        total_gross: "24.60",
        currency: "USD",
      },
      {
        id: "doc-2",
        number: "IN/2026/002",
        type: "IN",
        status: "COMPLETED",
        date: "2026-04-10",
        partner_name: "Beta",
        source_location_name: null,
        target_location_name: "Main",
        total_net: "40.00",
        total_tax: "9.20",
        total_gross: "49.20",
        currency: "USD",
      },
    ],
  };
}

/** one group with USD + EUR documents — flat sums must not exist. */
function buildMultiCurrencyResponse(): RegisterResponse {
  const base = buildRegisterResponse();
  return {
    ...base,
    groups: [
      {
        ...base.groups[0],
        total_net: null,
        total_tax: null,
        total_gross: null,
        currency: null,
        totals_by_currency: [
          {
            currency: "EUR",
            total_net: "20.00",
            total_tax: "4.60",
            total_gross: "24.60",
          },
          {
            currency: "USD",
            total_net: "40.00",
            total_tax: "9.20",
            total_gross: "49.20",
          },
        ],
      },
    ],
    summary: {
      has_shipments: false,
      scrap_documents: 0,
      documents_without_value: 0,
      total_documents: 2,
      total_net: null,
      total_tax: null,
      total_gross: null,
      currency: null,
      totals_by_currency: [
        {
          currency: "EUR",
          total_net: "20.00",
          total_tax: "4.60",
          total_gross: "24.60",
        },
        {
          currency: "USD",
          total_net: "40.00",
          total_tax: "9.20",
          total_gross: "49.20",
        },
      ],
    },
  };
}

/** A window in which the first receipt row was handed to a carrier. */
function shippedWindow() {
  const response = buildRegisterResponse();
  vi.mocked(documentsHooks.useDocumentRegister).mockReturnValue({
    data: {
      ...response,
      summary: { ...response.summary, has_shipments: true },
    },
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);
  const rows = buildRowsResponse();
  rows.items[0] = {
    ...rows.items[0],
    carrier: "InPost",
    tracking_number: "6200",
    tracking_url: "https://inpost.pl/sledzenie-przesylek?number=6200",
  };
  mockRows(rows);
}

function mockRows(data: RegisterRowsResponse | undefined) {
  vi.mocked(documentsHooks.useDocumentRegisterRows).mockReturnValue({
    data,
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof documentsHooks.useDocumentRegisterRows>);
}

function mockRowsFailed() {
  vi.mocked(documentsHooks.useDocumentRegisterRows).mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: true,
    error: new Error("boom"),
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof documentsHooks.useDocumentRegisterRows>);
}

describe("DocumentRegisterPage — totals columns", () => {
  const mockedUseDocumentRegister = vi.mocked(
    documentsHooks.useDocumentRegister,
  );

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: {
        id: "profile-1",
        organization_id: "org-1",
        name: "Default",
        numbering_format: "{TYPE}/{YEAR}/{SEQ:04d}",
        number_padding: 4,
        type_labels: null,
        default_unit: "pcs",
        default_currency: "USD",
        value_tracking_enabled: true,
        tax_handling: "GROSS",
        default_tax_rate: "23.00",
        require_partner_tax_id: false,
        approval_threshold: null,
        approval_required_for_types: [],
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
      isLoading: false,
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);

    mockedUseDocumentRegister.mockReturnValue({
      data: buildRegisterResponse(),
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);
    mockRows(buildRowsResponse());
  });

  it("keeps groups collapsed until the reader opens one", () => {
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    // The sums are there at once; the rows are not — a register over a year
    // of a busy warehouse used to arrive as every row at once.
    expect(screen.getAllByText("$60.00").length).toBeGreaterThan(0);
    expect(screen.queryByText("IN/2026/001")).not.toBeInTheDocument();
  });

  it("says the rows could not be loaded instead of calling the group empty", async () => {
    mockRowsFailed();
    const user = (await import("@testing-library/user-event")).default.setup();
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await user.click(screen.getByTestId("register-group-IN"));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/no documents/i)).not.toBeInTheDocument();
  });

  it("renders three totals columns per row when group is expanded", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await user.click(screen.getByTestId("register-group-IN"));

    await waitFor(() => {
      expect(screen.getByText("IN/2026/001")).toBeInTheDocument();
    });

    expect(screen.getByText("IN/2026/001")).toBeInTheDocument();
    expect(screen.getByText("IN/2026/002")).toBeInTheDocument();
    expect(screen.getAllByText("$20.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$4.60").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$24.60").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$49.20").length).toBeGreaterThan(0);
  });

  it("names the carrier and number on a phone, inside the row's own link", async () => {
    shippedWindow();
    const user = (await import("@testing-library/user-event")).default.setup();
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await user.click(screen.getByTestId("register-group-IN"));

    expect(await screen.findByText("InPost · 6200")).toBeInTheDocument();
    // No link inside the row's link: the document's card carries it.
    expect(
      screen.queryByRole("link", { name: /Track parcel/ }),
    ).not.toBeInTheDocument();
  });

  it("pages the rows when the group holds more than one page", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();
    const base = buildRegisterResponse();
    mockRows({ ...buildRowsResponse(), total: 120 });
    // The summary says the group holds 120 documents; the page serves 50.
    mockedUseDocumentRegister.mockReturnValue({
      data: {
        ...base,
        groups: [{ ...base.groups[0], document_count: 120 }],
        summary: { ...base.summary, total_documents: 120 },
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await user.click(screen.getByTestId("register-group-IN"));

    await waitFor(() => {
      expect(screen.getByText("IN/2026/001")).toBeInTheDocument();
    });
    // The group holds 120 documents, the page 50 — the pager says so.
    expect(screen.getByText(/Page 1 of 3/)).toBeInTheDocument();
  });

  it("renders group sum footer with aggregated totals", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await user.click(screen.getByTestId("register-group-IN"));

    await waitFor(() => {
      expect(screen.getByText("Group total")).toBeInTheDocument();
    });

    expect(screen.getByText("Group total")).toBeInTheDocument();
    expect(screen.getAllByText("$60.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$13.80").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$73.80").length).toBeGreaterThan(0);
  });

  it("renders em-dash for null totals", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();

    mockRows({
      total: 1,
      limit: 50,
      offset: 0,
      has_more: false,
      total_capped: false,
      items: [
        {
          ...buildRowsResponse().items[0],
          total_net: null,
          total_tax: null,
          total_gross: null,
        },
      ],
    });

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await user.click(screen.getByTestId("register-group-IN"));

    await waitFor(() => {
      expect(screen.getByText("IN/2026/001")).toBeInTheDocument();
    });

    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("never sums across currencies — per-currency totals instead", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();

    mockRows({
      total: 2,
      limit: 50,
      offset: 0,
      has_more: false,
      total_capped: false,
      items: [
        {
          ...buildRowsResponse().items[0],
          total_net: "20.00",
          total_tax: "4.60",
          total_gross: "24.60",
          currency: "EUR",
        },
        {
          ...buildRowsResponse().items[1],
          total_net: "40.00",
          total_tax: "9.20",
          total_gross: "49.20",
          currency: "USD",
        },
      ],
    });
    mockedUseDocumentRegister.mockReturnValue({
      data: buildMultiCurrencyResponse(),
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await user.click(screen.getByTestId("register-group-IN"));

    await waitFor(() => {
      expect(screen.getByText("IN/2026/001")).toBeInTheDocument();
    });

    // Document rows keep their own currencies.
    expect(screen.getAllByText("€24.60").length).toBeGreaterThan(0);
    expect(screen.getAllByText("$49.20").length).toBeGreaterThan(0);
    // No combined "$73.80" sum anywhere (flat totals are null → em-dash).
    expect(screen.queryByText("$73.80")).not.toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    // Per-currency lines in the group sum footer and summary cards.
    expect(screen.getByText("EUR")).toBeInTheDocument();
    expect(screen.getByText("USD")).toBeInTheDocument();
    expect(screen.getAllByText("€24.60").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("$49.20").length).toBeGreaterThanOrEqual(2);
  });
});

describe("DocumentRegisterPage empty buckets", () => {
  const mockedUseDocumentRegister = vi.mocked(
    documentsHooks.useDocumentRegister,
  );

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: undefined,
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    mockRows(undefined);
  });

  it("does not stack an empty currency line above every amount", async () => {
    // Documents with no value (transfers) form a bucket with a null currency
    // and no amounts. Rendered as one line per currency, that bucket became a
    // lone em dash hanging over Net, Tax and Gross.
    const base = buildRegisterResponse();
    mockedUseDocumentRegister.mockReturnValue({
      data: {
        ...base,
        summary: {
          ...base.summary,
          totals_by_currency: [
            {
              currency: "USD",
              total_net: "60.00",
              total_tax: "13.80",
              total_gross: "73.80",
            },
            {
              currency: null,
              total_net: null,
              total_tax: null,
              total_gross: null,
            },
          ],
        },
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await waitFor(() =>
      expect(screen.getAllByText("$60.00").length).toBeGreaterThan(0),
    );
    // The valueless bucket contributes nothing, so it must not print a row.
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("prints the one currency that has figures, not the flat null beside it", async () => {
    // The server will not add two buckets together, so a scope holding a
    // priceless document alongside eleven USD receipts came back with flat
    // nulls. Printing that null put an em dash where the month's total
    // belongs — on the one screen whose whole job is to prove the amounts.
    const base = buildRegisterResponse();
    const buckets = [
      {
        currency: "USD",
        total_net: "60.00",
        total_tax: "13.80",
        total_gross: "73.80",
      },
      {
        currency: null,
        total_net: null,
        total_tax: null,
        total_gross: null,
      },
    ];
    mockedUseDocumentRegister.mockReturnValue({
      data: {
        ...base,
        groups: [
          {
            ...base.groups[0],
            total_net: null,
            total_tax: null,
            total_gross: null,
            currency: null,
            totals_by_currency: buckets,
          },
        ],
        summary: {
          ...base.summary,
          total_net: null,
          total_tax: null,
          total_gross: null,
          currency: null,
          totals_by_currency: buckets,
        },
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    // Summary and group header both read the one valued bucket.
    await waitFor(() =>
      expect(screen.getAllByText("$73.80").length).toBeGreaterThan(0),
    );
    expect(screen.getAllByText("$60.00").length).toBeGreaterThan(0);
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("names the group of documents that have no partner", async () => {
    // Grouped by partner, documents without one produced a row called "—".
    // The shape here is the one the API sends for that bucket: an empty
    // grouping key and no label at all. An earlier version of this test
    // asserted against `label: ""`, which the backend never produced.
    const base = buildRegisterResponse();
    mockedUseDocumentRegister.mockReturnValue({
      data: {
        ...base,
        group_by: "partner",
        groups: [
          { ...base.groups[0], key: "", label: null, document_count: 8 },
        ],
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await waitFor(() =>
      expect(screen.getByText("No partner")).toBeInTheDocument(),
    );
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("names the group of documents that have no location", async () => {
    // Same nameless bucket, reached by grouping on location: "No partner"
    // would be the wrong sentence for it.
    const base = buildRegisterResponse();
    mockedUseDocumentRegister.mockReturnValue({
      data: {
        ...base,
        group_by: "location",
        groups: [
          { ...base.groups[0], key: "", label: null, document_count: 3 },
        ],
      },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);

    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    await waitFor(() =>
      expect(screen.getByText("No location")).toBeInTheDocument(),
    );
  });
});

/**
 * The register opens on the reader's own month-to-date window. Built through
 * `toISOString()`, both ends answered in UTC: east of Greenwich after
 * midnight the window began on the last day of the previous month and
 * ended yesterday.
 */
describe("DocumentRegisterPage — the day window it opens with", () => {
  it("starts the month and ends today where the reader is", () => {
    vi.mocked(documentsHooks.useDocumentRegister).mockReturnValue({
      data: buildRegisterResponse(),
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: undefined,
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    mockRows(undefined);

    const original = process.env.TZ;
    process.env.TZ = "Europe/Warsaw";
    vi.useFakeTimers();
    // 00:30 on 11 September 2026 local is still 22:30 on the 10th in UTC.
    vi.setSystemTime(new Date(2026, 8, 11, 0, 30));
    try {
      render(
        <HeaderHarness>
          <DocumentRegisterPage />
        </HeaderHarness>,
      );

      expect(screen.getByLabelText("From")).toHaveTextContent("Sep 1, 2026");
      expect(screen.getByLabelText("To")).toHaveTextContent("Sep 11, 2026");
    } finally {
      vi.useRealTimers();
      process.env.TZ = original;
    }
  });
});

/**
 * The desktop register is a table, and the three money columns finally have
 * headings. Built from `div`s, a reader told net from gross by noticing that
 * one number is larger, and a screen reader was given no cell-to-heading
 * association at all (§14.1).
 *
 * jsdom answers every media query with `false`, so the tests above all
 * exercise the stacked branch; this one says what the other one renders.
 */
describe("DocumentRegisterPage — the desktop branch is a table", () => {
  const mockedUseDocumentRegister = vi.mocked(
    documentsHooks.useDocumentRegister,
  );

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockImplementation((query: string) => ({
        matches: true,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        onchange: null,
        dispatchEvent: vi.fn(),
      })),
    );
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: null,
      isLoading: false,
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    mockedUseDocumentRegister.mockReturnValue({
      data: buildRegisterResponse(),
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);
    mockRows(buildRowsResponse());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("names every money column", () => {
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    for (const name of [/net/i, /tax|vat/i, /gross/i]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
  });

  it("puts each group in its own tbody rather than its own box", () => {
    const { container } = render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect(table?.querySelectorAll("tbody").length).toBeGreaterThan(0);
  });

  it("leaves carrier and tracking out of a window nothing was shipped in", () => {
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    expect(
      screen.queryByRole("columnheader", { name: "Carrier" }),
    ).not.toBeInTheDocument();
  });

  it("shows the carrier and a tracking link once something was shipped", async () => {
    shippedWindow();
    const user = (await import("@testing-library/user-event")).default.setup();
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    expect(
      screen.getByRole("columnheader", { name: "Carrier" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "Tracking" }),
    ).toBeInTheDocument();
    await user.click(screen.getByTestId("register-group-IN"));

    const link = await screen.findByRole("link", { name: /Track parcel 6200/ });
    expect(link).toHaveAttribute(
      "href",
      "https://inpost.pl/sledzenie-przesylek?number=6200",
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByText("InPost")).toBeInTheDocument();
    // The row without a shipment says so instead of leaving a hole.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders one branch, not both", () => {
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    // `hidden lg:block` would leave the stacked branch in the DOM beside the
    // table: a register of hundreds of rows twice over, and a screen reader
    // walking it twice.
    expect(screen.getAllByTestId("register-group-IN")).toHaveLength(1);
  });
});

describe("DocumentRegisterPage — what the totals leave out or fold in", () => {
  function windowWith(summary: {
    scrap_documents: number;
    documents_without_value: number;
  }) {
    const response = buildRegisterResponse();
    vi.mocked(documentsHooks.useDocumentRegister).mockReturnValue({
      data: { ...response, summary: { ...response.summary, ...summary } },
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);
    mockRows(buildRowsResponse());
  }

  it("says the month total includes scrap, at what the write-off cost", () => {
    windowWith({ scrap_documents: 2, documents_without_value: 0 });
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    expect(
      screen.getByText(/Scrap documents in these totals: 2/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("labels the Net figure for what it adds when a write-off is in it", () => {
    windowWith({ scrap_documents: 2, documents_without_value: 0 });
    const { unmount } = render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    expect(screen.getByText("Net, write-offs included")).toBeInTheDocument();
    unmount();

    windowWith({ scrap_documents: 0, documents_without_value: 0 });
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );
    expect(screen.queryByText("Net, write-offs included")).toBeNull();
    expect(screen.getAllByText("Net").length).toBeGreaterThan(0);
  });

  it("counts the documents posted without a price, so a total is not read as complete", () => {
    windowWith({ scrap_documents: 0, documents_without_value: 1 });
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      /Documents posted without a price: 1/,
    );
    expect(screen.queryByText(/Scrap documents/)).not.toBeInTheDocument();
  });

  it("stays quiet when every document carries a value", () => {
    windowWith({ scrap_documents: 0, documents_without_value: 0 });
    render(
      <HeaderHarness>
        <DocumentRegisterPage />
      </HeaderHarness>,
    );

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
