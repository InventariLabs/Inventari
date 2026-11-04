import { useSyncExternalStore } from "react";

// There is one reader on a page (the `qr-reader` element), so whether its
// camera has a torch is one fact, read by whichever view draws the button
// without every view being handed it through its props.
let torchAvailable = false;
const torchListeners = new Set<() => void>();

export function setTorchAvailable(available: boolean) {
  if (available === torchAvailable) return;
  torchAvailable = available;
  torchListeners.forEach((notify) => notify());
}

/**
 * Whether the camera that started has a torch to switch — the track says so
 * before any button is drawn, so a phone without one is never offered it.
 */
export function useTorchAvailable(): boolean {
  return useSyncExternalStore(
    (notify) => {
      torchListeners.add(notify);
      return () => torchListeners.delete(notify);
    },
    () => torchAvailable,
  );
}
