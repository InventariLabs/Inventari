import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

/**
 * Minimal wrapper for `renderHook` on hooks that read server state.
 *
 * `src/test/utils.tsx` pulls in the router, i18n and the module context —
 * more than a hook test needs, and more than a test mocking one of those can
 * tolerate. This one only provides a query client.
 */
export function QueryWrapper({ children }: { children: React.ReactNode }) {
  const [queryClient] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { retry: false } },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
