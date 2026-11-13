import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import i18n from "@/i18n/config";
import type { MockedFunction } from "vitest";
import axios, { type AxiosResponse } from "axios";
import AddItemModal from "./AddItemModal";
import { shoppingListsApi } from "@/modules/shopping_lists/api/shopping-lists";
import { uomsApi } from "@/lib/api/admin";
import { toast } from "sonner";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock API and toast
vi.mock("@/modules/shopping_lists/api/shopping-lists", () => ({
  shoppingListsApi: {
    addItem: vi.fn(),
  },
}));
vi.mock("@/lib/api/admin", () => ({
  uomsApi: {
    getAll: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}));

// Mock hooks/queries - provides useFlatUoms
vi.mock("@/hooks/queries", () => ({
  useFlatUoms: () => ({
    data: [
      { id: "1", name: "kg", abbreviation: "kg" },
      { id: "2", name: "pcs", abbreviation: "pcs" },
    ],
    isLoading: false,
  }),
  queryKeys: {},
}));

// The picker's own popover is its own suite's business; here it is the value
// it hands back, and the refusal it prints.
vi.mock("@/modules/shared/components/UomSelect", () => ({
  UomSelect: ({
    value,
    onChange,
    error,
  }: {
    value: string | null;
    onChange: (id: string, uom: { id: string; symbol: string }) => void;
    error?: string;
  }) => (
    <>
      <select
        aria-label="Unit"
        value={value ?? ""}
        onChange={(e) =>
          onChange(e.target.value, { id: e.target.value, symbol: "kg" })
        }
      >
        <option value="">Choose</option>
        <option value="uom-kg">kg</option>
      </select>
      {error && <p>{error}</p>}
    </>
  ),
}));

const chooseUnit = () =>
  fireEvent.change(screen.getByRole("combobox", { name: "Unit" }), {
    target: { value: "uom-kg" },
  });

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
);

describe("AddItemModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (uomsApi.getAll as MockedFunction<typeof uomsApi.getAll>).mockResolvedValue(
      [],
    );
  });

  it("should render add item modal", () => {
    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={() => {}} />,
      {
        wrapper,
      },
    );

    expect(screen.getByText(/Add to list/i)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/e.g. Milk, Bread, Ice cream…/i),
    ).toBeInTheDocument();
  });

  it("keeps a fraction being typed — the dot step's empty report is not a zero", () => {
    // While "2.5" is typed, the number field reports the dot step
    // as "". The form used to answer that with `parseFloat("") || 0`, which
    // rewrote the field to "0" mid-typing and ate the dot.
    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={() => {}} />,
      {
        wrapper,
      },
    );

    const field = screen.getByRole("spinbutton", { name: /quantity/i });
    fireEvent.change(field, { target: { value: "2" } });
    fireEvent.change(field, { target: { value: "" } });

    expect(field).toHaveValue(null);

    fireEvent.change(field, { target: { value: "2.5" } });
    expect(field).toHaveValue(2.5);
  });

  it("should call API when adding item", async () => {
    (
      shoppingListsApi.addItem as MockedFunction<
        typeof shoppingListsApi.addItem
      >
    ).mockResolvedValue({
      id: "new-item",
      shopping_list_id: "1",
      item_id: null,
      category_id: null,
      name: "Cheese",
      quantity: "1",
      uom_id: null,
      uom: null,
      notes: null,
      estimated_price: null,
      priority: 0,
      source: "manual",
      is_purchased: false,
      purchased_at: null,
      purchased_by: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      category: null,
    });

    const onSuccess = vi.fn();
    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={onSuccess} />,
      { wrapper },
    );

    const nameInput = screen.getByPlaceholderText(
      /e.g. Milk, Bread, Ice cream…/i,
    );
    fireEvent.change(nameInput, { target: { value: "Cheese" } });

    chooseUnit();
    const addBtn = screen.getByRole("button", { name: /Add/i });
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it("lets a fraction the store holds through — half a kilo of flour", async () => {
    // The form was the one place a person types a quantity, and it kept
    // the column's old integer rule: 0.5 left the Add button dead with no
    // message, while the store held three decimals and the catalogue
    // speaks in measured units.
    (
      shoppingListsApi.addItem as MockedFunction<
        typeof shoppingListsApi.addItem
      >
    ).mockResolvedValue({
      id: "new-item",
      shopping_list_id: "1",
      item_id: null,
      category_id: null,
      name: "Flour",
      quantity: "0.500",
      uom_id: null,
      uom: null,
      notes: null,
      estimated_price: null,
      priority: 0,
      source: "manual",
      is_purchased: false,
      purchased_at: null,
      purchased_by: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      category: null,
    });

    const onSuccess = vi.fn();
    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={onSuccess} />,
      { wrapper },
    );

    fireEvent.change(
      screen.getByPlaceholderText(/e.g. Milk, Bread, Ice cream…/i),
      { target: { value: "Flour" } },
    );
    const qty = screen.getByLabelText(/Quantity/i);
    fireEvent.change(qty, { target: { value: "0.5" } });

    chooseUnit();
    const addBtn = screen.getByRole("button", { name: /Add/i });
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(shoppingListsApi.addItem).toHaveBeenCalledWith(
        "1",
        expect.objectContaining({ name: "Flour", quantity: 0.5 }),
      );
    });
  });

  it("stops offering a quantity under the store's step — 0.0001 stays here", async () => {
    // The field marked the value red but the Add button stayed live, so
    // 0.0001 left as a request and came back as the server's refusal.
    // The floor is the same one the backend stores at (QUANTITY_STEP,
    // mirrored from validators.py and guarded by check:quantity-bounds).
    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={() => {}} />,
      { wrapper },
    );

    fireEvent.change(
      screen.getByPlaceholderText(/e.g. Milk, Bread, Ice cream…/i),
      { target: { value: "Saffron" } },
    );
    const qty = screen.getByRole("spinbutton", { name: /quantity/i });
    fireEvent.change(qty, { target: { value: "0.0001" } });

    expect(qty).toHaveAttribute("min", "0.001");
    expect(screen.getByText(/must be at least 0.001/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Add/i }));

    await waitFor(() => {
      expect(shoppingListsApi.addItem).not.toHaveBeenCalled();
    });
  });

  it("lets the store's step itself through — 0.001 is a number the column holds", () => {
    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={() => {}} />,
      { wrapper },
    );

    fireEvent.change(
      screen.getByPlaceholderText(/e.g. Milk, Bread, Ice cream…/i),
      { target: { value: "Saffron" } },
    );
    fireEvent.change(screen.getByRole("spinbutton", { name: /quantity/i }), {
      target: { value: "0.001" },
    });

    expect(screen.getByRole("button", { name: /Add/i })).toBeEnabled();
    expect(screen.queryByText(/must be at least/i)).not.toBeInTheDocument();
  });

  it("says what a quantity the column cannot hold is worth, instead of a 500", () => {
    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={() => {}} />,
      { wrapper },
    );

    fireEvent.change(
      screen.getByPlaceholderText(/e.g. Milk, Bread, Ice cream…/i),
      { target: { value: "Unobtainium" } },
    );
    const qty = screen.getByLabelText(/Quantity/i);
    fireEvent.change(qty, { target: { value: "1000000000" } });

    fireEvent.click(screen.getByRole("button", { name: /Add/i }));

    // The form repeats the schema's ceiling sentence (the backend answers
    // with the same words) instead of shipping the overflow to the driver.
    expect(
      screen.getByText(/above 999,999,999\.999 cannot be stored/i),
    ).toBeInTheDocument();
    expect(shoppingListsApi.addItem).not.toHaveBeenCalled();
  });

  it("writes the ceiling in the reader's decimal mark", async () => {
    // The sentence interpolated the raw constant, so a Polish interface read
    // "powyżej 999999999.999" — a dot where every other number, and the
    // server's own refusal for the same field, write a comma.
    await act(() => i18n.changeLanguage("pl"));
    try {
      render(
        <AddItemModal listId="1" onClose={() => {}} onSuccess={() => {}} />,
        { wrapper },
      );

      fireEvent.change(
        screen.getByPlaceholderText(/np\. Mleko, Chleb, Lody…/i),
        { target: { value: "Unobtainium" } },
      );
      fireEvent.change(screen.getByLabelText(/Ilość/i), {
        target: { value: "1000000000" },
      });

      fireEvent.click(screen.getByRole("button", { name: /Dodaj/i }));

      expect(
        screen.getByText(/powyżej 999\s999\s999,999 nie może zostać zapisana/i),
      ).toBeInTheDocument();
      expect(shoppingListsApi.addItem).not.toHaveBeenCalled();
    } finally {
      await act(() => i18n.changeLanguage("en"));
    }
  });

  it("should show the server error message when API fails", async () => {
    // A realistic axios error carrying a backend {code,message} detail —
    // extractApiError should surface the message instead of a raw string.
    const serverError = new axios.AxiosError(
      "Request failed",
      "ERR_BAD_REQUEST",
      undefined,
      undefined,
      {
        status: 400,
        data: {
          detail: {
            code: "VALIDATION_ERROR",
            message: "Item already on this list",
          },
        },
      } as unknown as AxiosResponse,
    );
    (
      shoppingListsApi.addItem as MockedFunction<
        typeof shoppingListsApi.addItem
      >
    ).mockRejectedValue(serverError);

    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={() => {}} />,
      {
        wrapper,
      },
    );

    const nameInput = screen.getByPlaceholderText(
      /e.g. Milk, Bread, Ice cream…/i,
    );
    fireEvent.change(nameInput, { target: { value: "Cheese" } });

    chooseUnit();
    const addBtn = screen.getByRole("button", { name: /Add/i });
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Item already on this list");
    });
  });

  it("refuses an entry with a quantity and no unit, and sends the unit once chosen", async () => {
    // "QA Milk 1" with the unit left at "Select unit…" was stored and
    // listed as "1 —": one piece, one pack or one kilogram, nobody knew.
    (
      shoppingListsApi.addItem as MockedFunction<
        typeof shoppingListsApi.addItem
      >
    ).mockResolvedValue({} as never);
    const onSuccess = vi.fn();
    render(
      <AddItemModal listId="1" onClose={() => {}} onSuccess={onSuccess} />,
      { wrapper },
    );
    fireEvent.change(
      screen.getByPlaceholderText(/e.g. Milk, Bread, Ice cream…/i),
      { target: { value: "QA Milk" } },
    );
    // Not while the name is being typed — only once Add is pressed.
    expect(screen.queryByText("Choose a unit")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Add/i }));
    expect(screen.getByText("Choose a unit")).toBeInTheDocument();
    expect(shoppingListsApi.addItem).not.toHaveBeenCalled();

    chooseUnit();
    expect(screen.queryByText("Choose a unit")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Add/i }));
    await waitFor(() => {
      expect(shoppingListsApi.addItem).toHaveBeenCalledWith(
        "1",
        expect.objectContaining({ name: "QA Milk", uom_id: "uom-kg" }),
      );
    });
  });
});
