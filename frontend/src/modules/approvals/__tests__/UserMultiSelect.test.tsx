import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UserMultiSelect } from "../components/UserMultiSelect";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const members = [
  {
    id: "u-1",
    email: "alice@example.com",
    full_name: "Alice",
    role: "admin",
  },
  {
    id: "u-2",
    email: "bob@example.com",
    full_name: "Bob",
    role: "manager",
  },
  {
    id: "u-3",
    email: "carol@example.com",
    full_name: null,
    role: "user",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  server.resetHandlers();
  server.use(
    http.get("/api/v1/users/org-members", () =>
      HttpResponse.json(onePage(members)),
    ),
  );
});

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

const openPopover = () => {
  fireEvent.click(screen.getByText("Add Approver"));
};

describe("UserMultiSelect", () => {
  it("renders a badge for each already-selected user", async () => {
    render(<UserMultiSelect selectedUserIds={["u-1"]} onChange={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    expect(await screen.findByText("Alice")).toBeInTheDocument();
  });

  it("falls back to email when full_name is null", async () => {
    render(<UserMultiSelect selectedUserIds={["u-3"]} onChange={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    expect(await screen.findByText("carol@example.com")).toBeInTheDocument();
  });

  it("keeps a badge inside its column: the name gives way, the remove button does not", async () => {
    // jsdom lays nothing out, so the contract is the classes: on a 375 px
    // stage card the column is narrower than 180 px of name.
    render(<UserMultiSelect selectedUserIds={["u-1"]} onChange={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    const name = await screen.findByText("Alice");
    expect(name).toHaveClass("min-w-0", "truncate");
    expect(name.parentElement).toHaveClass("max-w-full");
    expect(screen.getByLabelText("Remove approver")).toHaveClass("shrink-0");
  });

  it("removes a user when the X button is clicked", async () => {
    const onChange = vi.fn();
    render(
      <UserMultiSelect selectedUserIds={["u-1", "u-2"]} onChange={onChange} />,
      { wrapper: createWrapper() },
    );
    const removeButtons = await screen.findAllByLabelText("Remove approver");
    fireEvent.click(removeButtons[0]);
    expect(onChange).toHaveBeenCalledWith(["u-2"]);
  });

  it("opens the popover and lists available users", async () => {
    render(<UserMultiSelect selectedUserIds={["u-1"]} onChange={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    openPopover();
    // Bob and Carol are not yet selected, so they should be in the popover.
    expect(await screen.findByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("carol@example.com")).toBeInTheDocument();
  });

  it("adds a user when their row is clicked in the popover", async () => {
    const onChange = vi.fn();
    render(<UserMultiSelect selectedUserIds={["u-1"]} onChange={onChange} />, {
      wrapper: createWrapper(),
    });
    openPopover();
    const bobRow = await screen.findByText("Bob");
    fireEvent.click(bobRow.closest("button")!);
    expect(onChange).toHaveBeenCalledWith(["u-1", "u-2"]);
  });

  it("filters users by search query (name and email)", async () => {
    render(<UserMultiSelect selectedUserIds={[]} onChange={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    openPopover();
    const search = await screen.findByPlaceholderText("Search users…");
    fireEvent.change(search, { target: { value: "bob" } });
    await waitFor(() => {
      expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    });
    expect(screen.getByText("Bob")).toBeInTheDocument();
  });

  it("filters by email substring", async () => {
    render(<UserMultiSelect selectedUserIds={[]} onChange={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    openPopover();
    const search = await screen.findByPlaceholderText("Search users…");
    fireEvent.change(search, { target: { value: "carol@" } });
    await waitFor(() => {
      expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    });
    expect(screen.getByText("carol@example.com")).toBeInTheDocument();
  });

  it("shows the no-users-found message when search has no matches", async () => {
    render(<UserMultiSelect selectedUserIds={[]} onChange={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    openPopover();
    const search = await screen.findByPlaceholderText("Search users…");
    fireEvent.change(search, { target: { value: "zzznomatch" } });
    expect(await screen.findByText("No users found")).toBeInTheDocument();
  });

  it("does not list already-selected users in the popover", async () => {
    render(
      <UserMultiSelect selectedUserIds={["u-1", "u-2"]} onChange={vi.fn()} />,
      { wrapper: createWrapper() },
    );
    openPopover();
    await screen.findByText("carol@example.com");
    // Alice and Bob are pre-selected — they must not be in the available list.
    const popoverContent = screen
      .getByText("carol@example.com")
      .closest("button")!.parentElement!.parentElement!;
    expect(within(popoverContent).queryByText("Alice")).not.toBeInTheDocument();
    expect(within(popoverContent).queryByText("Bob")).not.toBeInTheDocument();
  });

  it("says all users are already selected instead of 'no users found'", async () => {
    render(
      <UserMultiSelect
        selectedUserIds={["u-1", "u-2", "u-3"]}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    openPopover();
    expect(
      await screen.findByText("All users already selected"),
    ).toBeInTheDocument();
    expect(screen.queryByText("No users found")).not.toBeInTheDocument();
  });

  it("says the people could not be loaded instead of listing nobody", async () => {
    server.use(
      http.get(
        "/api/v1/users/org-members",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );
    render(<UserMultiSelect selectedUserIds={[]} onChange={vi.fn()} />, {
      wrapper: createWrapper(),
    });
    openPopover();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("No users found")).not.toBeInTheDocument();
  });
});
