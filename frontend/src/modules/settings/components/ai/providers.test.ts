import { describe, it, expect } from "vitest";

import {
  PROVIDERS,
  PROVIDER_GROUPS,
  providerDefaultCapabilities,
  getProviderDescriptor,
} from "@/modules/settings/components/ai/providers";

describe("providers", () => {
  it("exposes 17 providers", () => {
    expect(PROVIDERS).to.have.lengthOf(17);
  });

  it("each provider has a unique id", () => {
    const ids = PROVIDERS.map((p) => p.id);
    expect(new Set(ids).size).to.equal(ids.length);
  });

  it("each provider belongs to a known group", () => {
    const groupIds = new Set(PROVIDER_GROUPS.map((g) => g.id));
    for (const p of PROVIDERS) {
      expect(
        groupIds.has(p.group),
        `${p.id} has unknown group ${p.group}`,
      ).to.equal(true);
    }
  });

  it("providerDefaultCapabilities handles every provider", () => {
    for (const p of PROVIDERS) {
      // Should not throw — every provider is covered.
      const caps = providerDefaultCapabilities(p.id);
      expect(Array.isArray(caps)).to.equal(true);
    }
  });

  it("vision-capable providers default to both capabilities", () => {
    expect(providerDefaultCapabilities("openai")).to.include("vision");
    expect(providerDefaultCapabilities("anthropic")).to.include("vision");
    expect(providerDefaultCapabilities("google")).to.include("vision");
  });

  it("local providers default to text-only", () => {
    expect(providerDefaultCapabilities("ollama")).to.not.include("vision");
    expect(providerDefaultCapabilities("vllm")).to.not.include("vision");
  });

  it("getProviderDescriptor returns by id", () => {
    expect(getProviderDescriptor("openai")?.name).to.equal("OpenAI");
    // Unknown id returns undefined — cast to satisfy the LlmProvider union.
    expect(getProviderDescriptor("nonexistent" as never)).toBeUndefined();
  });

  it("cloud providers have docsUrl", () => {
    const openai = getProviderDescriptor("openai");
    expect(openai?.docsUrl).to.match(/openai\.com/);
  });

  it("every provider has defaultBaseUrl (possibly empty)", () => {
    for (const p of PROVIDERS) {
      expect(typeof p.defaultBaseUrl).to.equal("string");
    }
  });

  it("the MiMo preset points at the host Xiaomi's API answers on", () => {
    // api.mimo.mi.com has no DNS record; keeping the preset made Test
    // report the provider unreachable before a key was ever checked.
    expect(getProviderDescriptor("mimo")?.defaultBaseUrl).to.equal(
      "https://api.xiaomimimo.com/v1",
    );
  });
});
