import { describe, it, expect, beforeEach } from "vitest";
import { useScanStore } from "./scanStore";

const mockContext = { id: "s1", name: "Fridge", icon: "❄️", type_code: "LOC" };

describe("useScanStore", () => {
  beforeEach(() => {
    useScanStore.setState({
      owner: null,
      storageContext: null,
      lastStorageId: null,
      lastCategoryId: null,
    });
  });

  it("has correct initial state", () => {
    const state = useScanStore.getState();
    expect(state.storageContext).toBeNull();
    expect(state.lastStorageId).toBeNull();
    expect(state.lastCategoryId).toBeNull();
  });

  it("setStorageContext stores context", () => {
    useScanStore.getState().setStorageContext(mockContext);
    expect(useScanStore.getState().storageContext).toEqual(mockContext);
  });

  it("clearStorageContext removes context", () => {
    useScanStore.getState().setStorageContext(mockContext);
    useScanStore.getState().clearStorageContext();
    expect(useScanStore.getState().storageContext).toBeNull();
  });

  it("setLastUsed stores storageId and categoryId", () => {
    useScanStore.getState().setLastUsed("s1", "c1");
    const state = useScanStore.getState();
    expect(state.lastStorageId).toBe("s1");
    expect(state.lastCategoryId).toBe("c1");
  });

  it("setLastUsed without a category clears the remembered one", () => {
    // A product saved without a category says "this one had none" — carrying
    // the remembered category forward would file the next product under it.
    useScanStore.setState({ lastCategoryId: "c-existing" });
    useScanStore.getState().setLastUsed("s2");
    expect(useScanStore.getState().lastCategoryId).toBeNull();
  });

  it("clearLastUsed forgets the shelf and the category", () => {
    useScanStore.getState().setLastUsed("s1", "c1");
    useScanStore.getState().clearLastUsed();
    const state = useScanStore.getState();
    expect(state.lastStorageId).toBeNull();
    expect(state.lastCategoryId).toBeNull();
    // The scan context is a different memory and stays.
    useScanStore.getState().setStorageContext(mockContext);
    useScanStore.getState().clearLastUsed();
    expect(useScanStore.getState().storageContext).toEqual(mockContext);
  });

  it("keeps the memory for its owner and forgets it for anybody else", () => {
    useScanStore.getState().claimFor("anna:Acme");
    useScanStore.getState().setLastUsed("s1", "c1");
    useScanStore.getState().setStorageContext(mockContext);

    useScanStore.getState().claimFor("anna:Acme");
    expect(useScanStore.getState().lastStorageId).toBe("s1");

    useScanStore.getState().claimFor("ben:Acme");
    const state = useScanStore.getState();
    expect(state.owner).toBe("ben:Acme");
    expect(state.storageContext).toBeNull();
    expect(state.lastStorageId).toBeNull();
    expect(state.lastCategoryId).toBeNull();
  });

  it("forgets a memory nobody can vouch for", () => {
    // What a device stored before the memory knew its owner: it could be
    // anybody's, and a shelf from another organization is worse than none.
    useScanStore.setState({ lastStorageId: "s1", lastCategoryId: "c1" });

    useScanStore.getState().claimFor("anna:Acme");
    expect(useScanStore.getState().lastStorageId).toBeNull();
  });
});
