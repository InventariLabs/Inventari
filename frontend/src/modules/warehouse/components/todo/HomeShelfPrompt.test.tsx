import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { HomeShelfPrompt } from "./HomeShelfPrompt";
import type { HomeShelfOffer } from "@/modules/warehouse/api/putaway";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const offer = {
  kind: "set",
  product_template_id: "p-1",
  product_name: "Flour",
  location_id: "l-1",
  location_name: "Cold Room",
  reason: null,
} as unknown as HomeShelfOffer;

describe("HomeShelfPrompt", () => {
  it("says the rule was written when the worker makes the location the home", async () => {
    server.use(
      http.put("/api/v1/warehouse/putaway/home-shelf", () =>
        HttpResponse.json({}),
      ),
    );
    const onDone = vi.fn();
    render(<HomeShelfPrompt offer={offer} isPhone={false} onDone={onDone} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Yes, make it the home" }),
    );

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("Cold Room is now the home of Flour"),
    );
  });
});
