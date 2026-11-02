import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { LabelPickerInput } from "./LabelPickerInput";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

/**
 * Through the real hook: the button awaits nothing, so a refused generate
 * has to reach the reader through the mutation factory's own toast — an
 * awaited `mutateAsync` there handed the refusal to nobody.
 */
describe("LabelPickerInput — a refused generate", () => {
  it("says why, in the server's words", async () => {
    server.use(
      http.get("/api/v1/labels/pool", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
      http.post("/api/v1/labels/pool/generate", () =>
        HttpResponse.json(
          { detail: "The label pool is full" },
          { status: 409 },
        ),
      ),
    );
    const onChange = vi.fn();
    render(<LabelPickerInput value="" onChange={onChange} />);

    fireEvent.click(screen.getByRole("button", { name: "Generate new label" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("The label pool is full"),
    );
    expect(onChange).not.toHaveBeenCalled();
  });
});
