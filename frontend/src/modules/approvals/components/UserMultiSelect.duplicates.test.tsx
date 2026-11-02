import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { UserMultiSelect } from "./UserMultiSelect";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const members = [
  {
    id: "u-1",
    email: "jan.a@example.com",
    full_name: "Jan Kowalski",
    role: "admin",
  },
  {
    id: "u-2",
    email: "jan.b@example.com",
    full_name: "Jan Kowalski",
    role: "user",
  },
  { id: "u-3", email: "ewa@example.com", full_name: "Ewa", role: "manager" },
];

const wrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

/**
 * Two members with one name are told apart by their e-mail on the badge,
 * the search can be cleared and the picker closed, and a member list that
 * failed to load offers a retry both beside the chosen people and inside the
 * picker. Two identical "Jan Kowalski" badges, or a failure that reads as
 * "nobody is selected", fails here.
 */
describe("UserMultiSelect — namesakes, search and a failed member list", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/users/org-members", () =>
        HttpResponse.json(onePage(members)),
      ),
    );
  });

  it("names namesakes by e-mail and a unique name alone", async () => {
    render(
      <UserMultiSelect
        selectedUserIds={["u-1", "u-2", "u-3"]}
        onChange={vi.fn()}
      />,
      { wrapper: wrapper() },
    );
    expect(
      await screen.findByText("Jan Kowalski (jan.a@example.com)"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Jan Kowalski (jan.b@example.com)"),
    ).toBeInTheDocument();
    expect(screen.getByText("Ewa")).toBeInTheDocument();
  });

  it("clears the search, adds a member, and closes the picker", async () => {
    const onChange = vi.fn();
    render(<UserMultiSelect selectedUserIds={[]} onChange={onChange} />, {
      wrapper: wrapper(),
    });
    fireEvent.click(screen.getByText("Add Approver"));
    const search = await screen.findByRole("textbox", {
      name: /search users/i,
    });
    fireEvent.change(search, { target: { value: "ewa" } });
    await waitFor(() =>
      expect(screen.queryByText(/jan\.a@example\.com/)).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /clear search/i }));
    expect(search).toHaveValue("");
    expect(await screen.findByText(/jan\.a@example\.com/)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/ewa@example\.com/));
    expect(onChange).toHaveBeenCalledWith(["u-3"]);

    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("offers a retry beside the chosen people and in the picker", async () => {
    let calls = 0;
    server.use(
      http.get("/api/v1/users/org-members", () => {
        calls += 1;
        return new HttpResponse(null, { status: 500 });
      }),
    );
    render(<UserMultiSelect selectedUserIds={["u-1"]} onChange={vi.fn()} />, {
      wrapper: wrapper(),
    });
    const outer = await screen.findByRole("button", { name: /try again/i });
    fireEvent.click(outer);
    await waitFor(() => expect(calls).toBe(2));

    fireEvent.click(screen.getByText("Add Approver"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /try again/i }));
    await waitFor(() => expect(calls).toBe(3));
  });
});
