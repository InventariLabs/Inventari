import { describe, it, expect, beforeEach } from "vitest";
import { useSettingsStore } from "./settingsStore";

describe("useSettingsStore", () => {
  beforeEach(() => {
    useSettingsStore.setState({
      publicUrl: window.location.origin,
      defaultLabelWidth: 50,
      defaultLabelHeight: 24,
      defaultLabelPrefix: "STM",
      defaultStoragePrefix: "LOC",
    });
  });

  it("has correct initial values", () => {
    const state = useSettingsStore.getState();
    expect(state.defaultLabelWidth).toBe(50);
    expect(state.defaultLabelHeight).toBe(24);
    expect(state.defaultLabelPrefix).toBe("STM");
    expect(state.defaultStoragePrefix).toBe("LOC");
  });

  it("setPublicUrl updates publicUrl", () => {
    useSettingsStore.getState().setPublicUrl("https://my.app");
    expect(useSettingsStore.getState().publicUrl).toBe("https://my.app");
  });

  it("setLabelDefaults updates width and height", () => {
    useSettingsStore.getState().setLabelDefaults(62, 29);
    const state = useSettingsStore.getState();
    expect(state.defaultLabelWidth).toBe(62);
    expect(state.defaultLabelHeight).toBe(29);
  });

  it("setPrefixes updates label and storage prefixes", () => {
    useSettingsStore.getState().setPrefixes("INV", "STO");
    const state = useSettingsStore.getState();
    expect(state.defaultLabelPrefix).toBe("INV");
    expect(state.defaultStoragePrefix).toBe("STO");
  });
});
