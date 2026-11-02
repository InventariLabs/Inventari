import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { InlineQueryError, QueryError, QueryResult } from "./QueryResult";
import type { UseQueryResult } from "@tanstack/react-query";

describe("QueryResult", () => {
  it("renders loading state with default fallback", () => {
    const mockQuery = {
      isLoading: true,
      isPending: true,
      isError: false,
      isSuccess: false,
      data: undefined,
      error: null,
    } as unknown as UseQueryResult<undefined>;

    const { container } = render(
      <QueryResult query={mockQuery} loadingFallback={<div>Loading…</div>}>
        {(data) => <div>{JSON.stringify(data)}</div>}
      </QueryResult>,
    );

    expect(container.textContent).toContain("Loading");
  });

  it("renders error state with custom fallback", () => {
    const mockQuery = {
      isLoading: false,
      isPending: false,
      isError: true,
      isSuccess: false,
      data: undefined,
      error: new Error("Test error"),
      refetch: () => Promise.resolve({ data: undefined, status: "error" }),
    } as unknown as UseQueryResult<undefined>;

    const { container } = render(
      <QueryResult query={mockQuery} errorFallback={<div>Error occurred</div>}>
        {(data) => <div>{JSON.stringify(data)}</div>}
      </QueryResult>,
    );

    expect(container.textContent).toContain("Error");
  });

  it("renders success state with data", () => {
    const mockData = [{ id: "1", name: "Test" }];
    const mockQuery = {
      isLoading: false,
      isPending: false,
      isError: false,
      isSuccess: true,
      data: mockData,
      error: null,
    } as unknown as UseQueryResult<typeof mockData>;

    render(
      <QueryResult query={mockQuery}>
        {(data) => <div>{data.length} items</div>}
      </QueryResult>,
    );

    expect(screen.getByText("1 items")).toBeInTheDocument();
  });

  it("renders empty state when no data and renderWhenEmpty false", () => {
    const mockQuery = {
      isLoading: false,
      isPending: false,
      isError: false,
      isSuccess: true,
      data: undefined,
      error: null,
    } as unknown as UseQueryResult<undefined>;

    const { container } = render(
      <QueryResult query={mockQuery} renderWhenEmpty={false}>
        {(data) => <div>{data ? "with data" : "no data"}</div>}
      </QueryResult>,
    );

    expect(container.textContent).not.toContain("with data");
    expect(container.textContent).not.toContain("no data");
  });

  it("renders empty array when renderWhenEmpty is true", () => {
    const mockQuery = {
      isLoading: false,
      isPending: false,
      isError: false,
      isSuccess: true,
      data: [],
      error: null,
    } as unknown as UseQueryResult<never[]>;

    render(
      <QueryResult query={mockQuery} renderWhenEmpty={true}>
        {(data) => <div>{data.length} items</div>}
      </QueryResult>,
    );

    expect(screen.getByText("0 items")).toBeInTheDocument();
  });

  it("accepts optional loadingFallback", () => {
    const mockQuery = {
      isLoading: true,
      isPending: true,
      isError: false,
      isSuccess: false,
      data: undefined,
      error: null,
    } as unknown as UseQueryResult<undefined>;

    const { container } = render(
      <QueryResult
        query={mockQuery}
        loadingFallback={<div>Custom Loading</div>}
      >
        {(_data) => <div>Data</div>}
      </QueryResult>,
    );

    expect(container.textContent).toContain("Custom");
  });

  it("accepts optional errorFallback", () => {
    const mockQuery = {
      isLoading: false,
      isPending: false,
      isError: true,
      isSuccess: false,
      data: undefined,
      error: new Error("Test"),
      refetch: () => Promise.resolve({ data: undefined, status: "error" }),
    };

    const { container } = render(
      <QueryResult
        query={mockQuery as unknown as UseQueryResult<undefined>}
        errorFallback={<div>Custom Error</div>}
      >
        {(_data) => <div>Data</div>}
      </QueryResult>,
    );

    expect(container.textContent).toContain("Custom");
  });

  it("renders children function with query data", () => {
    const mockQuery = {
      isLoading: false,
      isPending: false,
      isError: false,
      isSuccess: true,
      data: { id: "1", title: "Test Item" },
      error: null,
    } as unknown as UseQueryResult<{ id: string; title: string }>;

    render(
      <QueryResult query={mockQuery}>
        {(data) => <div>{data.title}</div>}
      </QueryResult>,
    );

    expect(screen.getByText("Test Item")).toBeInTheDocument();
  });
  it("announces itself — it stands where content was expected", () => {
    // A message that appears and leaves without a word is invisible to a screen
    // reader, and none of the module's error states announced anything.
    render(<QueryError />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("offers the inline error a retry, and withholds it from a refusal", () => {
    const refused = Object.assign(new Error("no"), {
      isAxiosError: true,
      response: { status: 403 },
    });
    const { rerender } = render(
      <InlineQueryError error={new Error("boom")} onRetry={() => {}} />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeInTheDocument();

    rerender(<InlineQueryError error={refused} onRetry={() => {}} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("retries from inside a form without submitting it", async () => {
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    const retryInline = vi.fn();
    const retryBlock = vi.fn();
    render(
      <form onSubmit={onSubmit}>
        <InlineQueryError error={new Error("boom")} onRetry={retryInline} />
        <QueryError onRetry={retryBlock} />
      </form>,
    );
    for (const button of screen.getAllByRole("button")) {
      await userEvent.click(button);
    }
    expect(retryInline).toHaveBeenCalledTimes(1);
    expect(retryBlock).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
