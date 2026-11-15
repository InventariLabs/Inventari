import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { ShelfLifeSlot } from "@/modules/maker/components/ShelfLifeSlot";
import type { Item } from "@/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));

const item = { template_id: "tpl-jam" } as unknown as Item;

function summary(defaultRecipeId: string | null) {
  server.use(
    http.get("*/api/v1/maker/bom/summary", () =>
      HttpResponse.json({
        items: [
          {
            template_id: "tpl-jam",
            has_bom: defaultRecipeId !== null,
            line_count: 1,
            default_recipe_id: defaultRecipeId,
          },
        ],
      }),
    ),
  );
}

describe("ShelfLifeSlot", () => {
  let saved: unknown;

  beforeEach(() => {
    saved = undefined;
    server.use(
      http.put(
        "*/api/v1/maker/production/shelf-lives/:id",
        async ({ request }) => {
          saved = await request.json();
          return HttpResponse.json({
            product_template_id: "tpl-jam",
            shelf_life_days: 180,
          });
        },
      ),
    );
  });

  it("saves the days typed on a made product when the field is left", async () => {
    summary("recipe-1");
    render(<ShelfLifeSlot data={{ item }} />);

    const field = await screen.findByTestId("maker-shelf-life-input");
    fireEvent.change(field, { target: { value: "180" } });
    fireEvent.blur(field);

    await waitFor(() => expect(saved).toEqual({ shelf_life_days: 180 }));
  });

  it("refuses a part of a day without saving it", async () => {
    summary("recipe-1");
    render(<ShelfLifeSlot data={{ item }} />);

    const field = await screen.findByTestId("maker-shelf-life-input");
    fireEvent.change(field, { target: { value: "1.5" } });
    fireEvent.blur(field);

    expect(
      await screen.findByText("Type a whole number of days, 1 or more."),
    ).toBeInTheDocument();
    expect(saved).toBeUndefined();
  });

  it("stays away from a product nobody makes", async () => {
    summary(null);
    render(<ShelfLifeSlot data={{ item }} />);

    await waitFor(() =>
      expect(screen.queryByTestId("maker-shelf-life-input")).toBeNull(),
    );
  });
});
