import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { render, screen, fireEvent } from "@/test/utils";
import DocumentRegisterPage from "./DocumentRegisterPage";
import * as documentsHooks from "@/modules/warehouse/hooks/useDocuments";
import { documentsApi } from "@/modules/warehouse/api/documents";
import { downloadBlob } from "@/utils/helpers";
import type {
  RegisterResponse,
  RegisterRowsResponse,
} from "@/modules/warehouse/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

vi.mock("@/hooks/useModulePageHeader", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useModulePageHeader")>()),
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

vi.mock("@/modules/warehouse/hooks/useDocuments", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/modules/warehouse/hooks/useDocuments")
  >()),
  useDocumentRegister: vi.fn(),
  useDocumentRegisterRows: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({ data: null, isLoading: false }),
}));

vi.mock("@/utils/helpers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/helpers")>()),
  downloadBlob: vi.fn(),
}));

// The calendar has its own tests; here only the date it reports matters.
vi.mock("@/components/ui/DateInput", () => ({
  DateInput: ({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: string;
    onChange: (value: string) => void;
  }) => (
    <label>
      {label}
      <input value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  ),
}));

const desktop = vi.hoisted(() => ({ value: false }));
vi.mock("@/hooks/useMediaQuery", () => ({
  useMediaQuery: () => desktop.value,
}));

function registerResponse(documentCount = 120): RegisterResponse {
  const totals = {
    currency: "USD",
    total_net: "60.00",
    total_tax: "13.80",
    total_gross: "73.80",
  };
  return {
    date_from: "2026-04-01",
    date_to: "2026-04-30",
    group_by: "type",
    groups: [
      {
        key: "IN",
        label: "IN",
        document_count: documentCount,
        ...totals,
        totals_by_currency: [totals],
      },
    ],
    summary: {
      has_shipments: false,
      scrap_documents: 0,
      documents_without_value: 0,
      total_documents: documentCount,
      ...totals,
      totals_by_currency: [totals],
    },
  };
}

function rowsResponse(): RegisterRowsResponse {
  return {
    total: 120,
    limit: 50,
    offset: 0,
    has_more: true,
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
    ],
  };
}

function lastRegisterParams() {
  const calls = vi.mocked(documentsHooks.useDocumentRegister).mock.calls;
  return calls[calls.length - 1][0];
}

function lastRowsOffset() {
  const calls = vi.mocked(documentsHooks.useDocumentRegisterRows).mock.calls;
  return (calls[calls.length - 1][0] as { offset: number }).offset;
}

/**
 * The register's filters, pager and export. Each test changes one control
 * and checks the request it produces: a type chip or a grouping that does
 * not reach the query, a pager that does not move the offset, a retry that
 * does not refetch, or a CSV export that fails without a word all fail here.
 */
describe.each([
  ["stacked", false],
  ["desktop", true],
])("DocumentRegisterPage — filters and pager (%s)", (_name, isDesktop) => {
  beforeEach(() => {
    vi.clearAllMocks();
    desktop.value = isDesktop;
    vi.mocked(documentsHooks.useDocumentRegister).mockReturnValue({
      data: registerResponse(),
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);
    vi.mocked(documentsHooks.useDocumentRegisterRows).mockReturnValue({
      data: rowsResponse(),
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegisterRows>);
  });

  afterEach(() => {
    desktop.value = false;
  });

  it("narrows the register to the type chip pressed, and back to all", async () => {
    const user = userEvent.setup();
    render(<DocumentRegisterPage />);
    expect(lastRegisterParams()).not.toHaveProperty("type");
    await user.click(screen.getByRole("button", { name: "Delivery" }));
    expect(lastRegisterParams()).toMatchObject({ type: "OUT" });
    await user.click(screen.getByRole("button", { name: "All" }));
    expect(lastRegisterParams()).not.toHaveProperty("type");
  });

  it("groups the register the way the reader chose", async () => {
    const user = userEvent.setup();
    render(<DocumentRegisterPage />);
    await user.click(screen.getByRole("button", { name: "Partner" }));
    expect(lastRegisterParams()).toMatchObject({ group_by: "partner" });
  });

  it("asks for the window between the two dates", () => {
    render(<DocumentRegisterPage />);
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-03-01" },
    });
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "2026-03-31" },
    });
    expect(lastRegisterParams()).toMatchObject({
      date_from: "2026-03-01",
      date_to: "2026-03-31",
    });
  });

  it("moves the group's rows a page on, and back", async () => {
    const user = userEvent.setup();
    render(<DocumentRegisterPage />);
    await user.click(screen.getByTestId("register-group-IN"));
    expect(lastRowsOffset()).toBe(0);
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(lastRowsOffset()).toBe(50);
    expect(screen.getByText(/Page 2 of 3/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Previous" }));
    expect(lastRowsOffset()).toBe(0);
  });

  it("refetches the group's rows from the retry", async () => {
    const refetch = vi.fn();
    vi.mocked(documentsHooks.useDocumentRegisterRows).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("boom"),
      refetch,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegisterRows>);
    const user = userEvent.setup();
    render(<DocumentRegisterPage />);
    await user.click(screen.getByTestId("register-group-IN"));
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe("DocumentRegisterPage — CSV export", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(documentsHooks.useDocumentRegister).mockReturnValue({
      data: registerResponse(2),
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegister>);
    vi.mocked(documentsHooks.useDocumentRegisterRows).mockReturnValue({
      data: rowsResponse(),
      isLoading: false,
      isError: false,
    } as unknown as ReturnType<typeof documentsHooks.useDocumentRegisterRows>);
  });

  it("downloads the register with the filters on screen", async () => {
    const blob = new Blob(["a,b"]);
    const spy = vi
      .spyOn(documentsApi, "getRegisterCsv")
      .mockResolvedValue(blob);
    const user = userEvent.setup();
    render(<DocumentRegisterPage />);
    await user.click(screen.getByRole("button", { name: "Receipt" }));
    await user.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "IN",
        status: "COMPLETED",
        output_format: "csv",
      }),
    );
    expect(downloadBlob).toHaveBeenCalledWith(
      blob,
      expect.stringMatching(
        /^register_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.csv$/,
      ),
    );
  });

  it("says so when the export fails, since the browser will not", async () => {
    vi.spyOn(documentsApi, "getRegisterCsv").mockRejectedValue(
      new AxiosError("Network Error", "ERR_NETWORK"),
    );
    const user = userEvent.setup();
    render(<DocumentRegisterPage />);
    await user.click(screen.getByRole("button", { name: "Export CSV" }));
    expect(toast.error).toHaveBeenCalledWith("Could not export the register");
    expect(downloadBlob).not.toHaveBeenCalled();
  });
});
