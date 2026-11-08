# Frontend Testing

This project uses **Vitest** and **React Testing Library** for automated testing.  
E2E tests are written with **Playwright** and run separately.

## Running Tests

In the `frontend` directory:

### Unit & Component Tests (Vitest)

- `npm run test` - Runs tests in watch mode.
- `npm run test:run` - Runs tests once (useful for CI).

### E2E Tests (Playwright)

E2E tests are located in `tests/e2e/` and are **excluded from Vitest**. They
write to whatever database the stack they run against serves, so run them on
the throwaway dev2 stack (ports +100, provisioned on demand) — from the repo
root:

```bash
make test-e2e-isolated
```

A bare `npx playwright test` targets the primary dev frontend instead
(`baseURL` defaults to `http://127.0.0.1:5173`) and pollutes the primary dev
database; reset that stack afterwards if you run it there. `make test-e2e` is
the same target without the isolation.

For visual debugging, with the isolated stack already up:

```bash
cd frontend && VITE_API_URL=http://127.0.0.1:5273 npx playwright test --ui
```

## Test Structure

- `src/test/setup.ts` - Global configuration (MSW, DOM cleanup).
- `src/test/mocks/` - API mocks using MSW.
- `*.test.ts` / `*.test.tsx` - Unit/component test files next to the code being tested or in dedicated folders.
- `tests/e2e/*.spec.ts` - Playwright E2E tests (excluded from Vitest via `vite.config.ts`).

## API Mocking (MSW)

All API requests are intercepted by Mock Service Worker. Handler definitions are located in `src/test/mocks/handlers.ts`. If you add a new endpoint, remember to add it to the handlers.

## Best Practices

1. **Test behavior, not implementation**: Focus on what the user sees (use `screen.getByRole`, `screen.getByText`).
2. **Use `act`**: When changing Zustand state or rendering components, ensure the code is wrapped in `act` (RTL usually does this automatically, but it's worth remembering for stores).
3. **Reset state**: Each test should be independent. We use `server.resetHandlers()` and reset stores in `beforeEach`.