import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ExclusionToggle } from "./ExclusionToggle";
import { signInWith, signOut } from "@/test/auth";

beforeEach(() => signInWith(["recipes:read", "recipes:write"]));
afterEach(() => {
  signOut();
  read.failed = false;
  read.refetch.mockClear();
});

const read = vi.hoisted(() => ({ failed: false, refetch: vi.fn() }));
vi.mock("@/modules/recipes/hooks/useMealPlans", () => ({
  useShoppingExclusions: () => ({
    data: read.failed ? undefined : [],
    isError: read.failed,
    refetch: read.refetch,
  }),
  useCreateShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteShoppingExclusion: () => ({ mutate: vi.fn(), isPending: false }),
}));

describe("ExclusionToggle", () => {
  it("offers the toggle once the exclusions are known", () => {
    render(<ExclusionToggle name="Salt" />);
    expect(screen.getByText("Always at home")).toBeInTheDocument();
  });

  it("offers a retry instead when the exclusions did not load", () => {
    // Every ingredient would read as "not excluded", and a press would
    // add an exclusion that already exists.
    read.failed = true;
    render(<ExclusionToggle name="Salt" />);

    expect(screen.queryByText("Always at home")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(read.refetch).toHaveBeenCalledTimes(1);
  });
});
