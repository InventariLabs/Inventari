import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SettingsState {
  publicUrl: string;
  setPublicUrl: (url: string) => void;
  defaultLabelWidth: number;
  defaultLabelHeight: number;
  setLabelDefaults: (width: number, height: number) => void;
  defaultLabelPrefix: string;
  defaultStoragePrefix: string;
  setPrefixes: (labelPrefix: string, storagePrefix: string) => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      publicUrl: window.location.origin,
      setPublicUrl: (publicUrl) => set({ publicUrl }),
      defaultLabelWidth: 50,
      defaultLabelHeight: 24,
      setLabelDefaults: (defaultLabelWidth, defaultLabelHeight) =>
        set({ defaultLabelWidth, defaultLabelHeight }),
      defaultLabelPrefix: "STM",
      defaultStoragePrefix: "LOC",
      setPrefixes: (defaultLabelPrefix, defaultStoragePrefix) =>
        set({ defaultLabelPrefix, defaultStoragePrefix }),
    }),
    {
      name: "inventari-settings",
      onRehydrateStorage: () => (state) => {
        // Always sync publicUrl with current origin after hydration
        if (state) {
          state.publicUrl = window.location.origin;
        }
      },
    },
  ),
);
