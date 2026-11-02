import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { SilencedHomeShelves } from "./SilencedHomeShelves";

const fixtures = vi.hoisted(() => ({
  silenced: undefined as Array<Record<string, unknown>> | undefined,
  unsilence: vi.fn(),
}));

vi.mock("@/modules/warehouse/hooks/usePutawayRules", () => ({
  useSilencedHomeShelves: () => ({ data: fixtures.silenced }),
  useUnsilenceHomeShelf: () => ({
    mutate: fixtures.unsilence,
    isPending: false,
  }),
}));

describe("SilencedHomeShelves", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fixtures.silenced = [
      { product_template_id: "tpl-rice", product_name: "Jasmine Rice" },
    ];
  });

  it("lists the products not asked about and asks again on request", async () => {
    render(<SilencedHomeShelves canWrite />);

    expect(screen.getByText("Jasmine Rice")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Ask again about Jasmine Rice" }),
    );

    expect(fixtures.unsilence).toHaveBeenCalledWith("tpl-rice");
  });

  it("offers no way back to an account that cannot write", () => {
    render(<SilencedHomeShelves canWrite={false} />);

    expect(screen.getByText("Jasmine Rice")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is absent while no product was silenced", () => {
    fixtures.silenced = [];
    const { container } = render(<SilencedHomeShelves canWrite />);

    expect(container).toBeEmptyDOMElement();
  });
});
