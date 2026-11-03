import { lazy, Suspense, type ComponentProps } from "react";

// The SDK is a large chunk that a phone screen like receiving or the product
// form does not otherwise load; the camera button needs it only once the
// screen is up, so it arrives after first paint instead of inside the
// screen's own budget.
const ScanToFill = lazy(() =>
  import("@/module-sdk").then((sdk) => ({ default: sdk.ScanToFill })),
);

/** `ScanToFill`, loaded after the screen that carries it has painted. */
export function LazyScanToFill(props: ComponentProps<typeof ScanToFill>) {
  return (
    <Suspense fallback={null}>
      <ScanToFill {...props} />
    </Suspense>
  );
}
