import { renderHook, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { queryKeys } from "@/hooks/queries/keys";
import { usersApi } from "@/lib/api/admin";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { useAssignableMembers } from "../useWorkItems";

const members = [
  { id: "u-1", email: "alice@example.com", full_name: "Alice", role: "admin" },
  { id: "u-2", email: "bob@example.com", full_name: null, role: "user" },
];

function setup() {
  server.use(
    http.get("/api/v1/users/org-members", () =>
      HttpResponse.json(onePage(members)),
    ),
  );
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, wrapper };
}

/** The approvals picker and the audit-log filters read the key like this. */
function useMembersLikeThePickers() {
  return useQuery({
    queryKey: queryKeys.users.orgMembers,
    queryFn: () => usersApi.getOrgMembers(),
    staleTime: 30_000,
  });
}

describe("useAssignableMembers shares the members cache entry", () => {
  it("names every member, falling back to the email", async () => {
    const { wrapper } = setup();
    const { result } = renderHook(() => useAssignableMembers(true), {
      wrapper,
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toEqual([
      { id: "u-1", name: "Alice" },
      { id: "u-2", name: "bob@example.com" },
    ]);
  });

  it("leaves full member records in the cache for the approvals picker", async () => {
    const { wrapper, queryClient } = setup();
    const { result } = renderHook(() => useAssignableMembers(true), {
      wrapper,
    });
    await waitFor(() => expect(result.current.data).toBeDefined());

    const { result: picker } = renderHook(() => useMembersLikeThePickers(), {
      wrapper,
    });
    expect(picker.current.data?.map((u) => u.full_name)).toEqual([
      "Alice",
      null,
    ]);
    expect(picker.current.data?.map((u) => u.email)).toEqual([
      "alice@example.com",
      "bob@example.com",
    ]);
    expect(queryClient.getQueryData(queryKeys.users.orgMembers)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ email: "alice@example.com" }),
      ]),
    );
  });

  it("names members when the picker filled the cache first", async () => {
    const { wrapper } = setup();
    const { result: picker } = renderHook(() => useMembersLikeThePickers(), {
      wrapper,
    });
    await waitFor(() => expect(picker.current.data).toBeDefined());

    const { result } = renderHook(() => useAssignableMembers(true), {
      wrapper,
    });
    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toEqual([
      { id: "u-1", name: "Alice" },
      { id: "u-2", name: "bob@example.com" },
    ]);
  });
});
