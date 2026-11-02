import { vi } from "vitest";

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();

  return {
    ...actual,
    QueryClient: class MockQueryClient extends actual.QueryClient {
      constructor(
        config: ConstructorParameters<typeof actual.QueryClient>[0] = {},
      ) {
        config.defaultOptions = config.defaultOptions || {};
        config.defaultOptions.queries = config.defaultOptions.queries || {};
        config.defaultOptions.queries.gcTime = 0;
        config.defaultOptions.queries.staleTime = 0;
        config.defaultOptions.queries.retry = false;

        config.defaultOptions.mutations = config.defaultOptions.mutations || {};
        config.defaultOptions.mutations.gcTime = 0;
        config.defaultOptions.mutations.retry = false;

        super(config);
      }
    },
  };
});
