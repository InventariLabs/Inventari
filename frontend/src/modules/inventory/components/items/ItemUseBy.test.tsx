import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { addWeeks, format } from "date-fns";
import { describe, it, expect } from "vitest";

import { render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import type { Item } from "@/types";
import ItemUseBy, { isOpenedRecord } from "./ItemUseBy";
import ExpiryChip from "./ExpiryChip";

function record(fields: Record<string, unknown>): Item {
  return {
    id: "item-1",
    name: "Flour",
    expiry_date: "2027-01-31",
    ...fields,
  } as unknown as Item;
}

const open = { opened: { at: "2026-10-01T09:00:00+00:00" } };

describe("isOpenedRecord", () => {
  it("reads the mark opening writes", () => {
    expect(isOpenedRecord(record({ metadata: open }))).toBe(true);
    expect(isOpenedRecord(record({ metadata: null }))).toBe(false);
    expect(isOpenedRecord(record({ metadata: { opened: {} } }))).toBe(false);
  });
});

describe("ItemUseBy", () => {
  it("saves a date for an opened package", async () => {
    const user = userEvent.setup();
    let body: unknown;
    server.use(
      http.put("*/items/item-1/use-by", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(record({}));
      }),
    );
    render(<ItemUseBy item={record({ metadata: open })} />);

    await user.click(screen.getByLabelText(/use by after opening/i));
    await user.click(screen.getAllByTestId("date-preset")[0]);
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(body).toEqual({
        use_by: format(addWeeks(new Date(), 1), "yyyy-MM-dd"),
      }),
    );
  });

  it("clears a date that was set", async () => {
    const user = userEvent.setup();
    let body: unknown;
    server.use(
      http.put("*/items/item-1/use-by", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(record({}));
      }),
    );
    render(
      <ItemUseBy
        item={record({ metadata: open, use_by_date: "2026-11-20" })}
      />,
    );

    await user.click(screen.getByRole("button", { name: /clear/i }));

    await waitFor(() => expect(body).toEqual({ use_by: null }));
  });
});

describe("ExpiryChip", () => {
  it("shows the date that counts, not the batch's, when the use-by is earlier", () => {
    render(
      <ExpiryChip
        item={{
          expiry_date: "2099-01-31",
          effective_expiry_date: "2000-01-05",
        }}
      />,
    );

    expect(screen.getByTestId("item-expiry")).toHaveAttribute(
      "data-expiry-state",
      "expired",
    );
  });

  it("falls back to the batch date for an answer that lacks the new field", () => {
    render(<ExpiryChip item={{ expiry_date: "2099-01-31" }} />);

    expect(screen.getByTestId("item-expiry")).toBeInTheDocument();
  });

  it("shows the fallback when the record has no date", () => {
    render(<ExpiryChip item={{}} fallback={<span>none</span>} />);

    expect(screen.getByText("none")).toBeInTheDocument();
  });
});
