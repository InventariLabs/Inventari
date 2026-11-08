import { Cloud, Server, Settings2, Shuffle, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { LlmCapability, LlmProvider } from "@/types/ai";

/**
 * Provider descriptor — single source of truth for the provider picker UI.
 * Mirrors backend LlmProvider enum (17 values: sixteen model providers and the
 * Jina page reader, which has no model client at all). Most providers route
 * through the OpenAI-compatible client; only `anthropic` and `google` use
 * native SDKs.
 */
type ProviderGroup = "cloud" | "aggregator" | "specialist" | "local" | "custom";

interface ProviderDescriptor {
  id: LlmProvider;
  name: string;
  /**
   * The catalogue key, for the one entry whose name is a description.
   *
   * Sixteen of the seventeen are brands: OpenAI, Anthropic, DeepSeek and the
   * rest are written the same way in every language, so their `name` is
   * their name. "Custom OpenAI-compatible" is not a brand — it says what
   * the entry is for, and a description belongs in the catalogue like the
   * line under it.
   */
  nameKey?: string;
  group: ProviderGroup;
  /** Lucide icon name fallback when no logo SVG is present. */
  icon?: string;
  /** Brand logo path under /public/logos/. Undefined for local/custom. */
  logo?: string;
  /** Pre-filled on tile click. Empty string for google (uses SDK). */
  defaultBaseUrl: string;
  /** Auto-seeded into model_name when the user hasn't typed one. */
  defaultModel?: string;
  /** API key input placeholder. */
  apiKeyPlaceholder?: string;
  /** "Get API key" external link. */
  docsUrl?: string;
  /**
   * Show the base URL input field. True for every provider that has a real
   * endpoint (cloud, aggregator, specialist, local, custom). False only for
   * providers that use a native SDK with no configurable base URL (Google
   * Gemini — the SDK derives the endpoint from the API key). Hiding the
   * field for SDK providers avoids an empty input that would mislead users
   * into thinking they need to fill it.
   */
  showBaseUrl: boolean;
  /**
   * Show the model field. False only for a provider that is not a model at
   * all — the reader's credential names a service, and a Model input with
   * another provider's placeholder would ask a question with no answer.
   */
  hasModel?: boolean;
  /** Whether this provider typically needs an API key (false for local). */
  needsApiKey: boolean;
}

/**
 * The catalog key describing what a provider is good for.
 *
 * The descriptions used to live in this file as English literals — sixteen of
 * them, on a screen translated into five languages.
 */
export const providerDescriptionKey = (id: LlmProvider): string =>
  `config.providerDescription.${id}`;

/**
 * The group headings. The icon is a component, not a character in the
 * translation: the labels used to carry an emoji inside the translated string
 * ("☁️ Cloud"), which no translator can be expected to keep and which is the
 * one place in the application that draws its icons that way.
 */
export const PROVIDER_GROUPS: ReadonlyArray<{
  id: ProviderGroup;
  labelKey: string;
  icon: LucideIcon;
}> = [
  { id: "cloud", labelKey: "config.groupCloud", icon: Cloud },
  { id: "aggregator", labelKey: "config.groupAggregator", icon: Shuffle },
  { id: "specialist", labelKey: "config.groupSpecialist", icon: Zap },
  { id: "local", labelKey: "config.groupLocal", icon: Server },
  { id: "custom", labelKey: "config.groupCustom", icon: Settings2 },
];

export const PROVIDERS: ReadonlyArray<ProviderDescriptor> = [
  // Cloud
  {
    id: "openai",
    name: "OpenAI",
    group: "cloud",
    logo: "/logos/openai.svg",
    defaultBaseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-4o",
    apiKeyPlaceholder: "sk-...",
    docsUrl: "https://platform.openai.com/api-keys",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "anthropic",
    name: "Anthropic",
    group: "cloud",
    logo: "/logos/anthropic.svg",
    defaultBaseUrl: "https://api.anthropic.com",
    defaultModel: "claude-sonnet-4-5",
    apiKeyPlaceholder: "sk-ant-...",
    docsUrl: "https://console.anthropic.com/settings/keys",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "google",
    name: "Google Gemini",
    group: "cloud",
    logo: "/logos/google.svg",
    defaultBaseUrl: "",
    defaultModel: "gemini-2.0-flash",
    docsUrl: "https://aistudio.google.com/apikey",
    showBaseUrl: false,
    needsApiKey: true,
  },

  // Aggregator
  {
    id: "openrouter",
    name: "OpenRouter",
    group: "aggregator",
    logo: "/logos/openrouter.svg",
    defaultBaseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "google/gemini-2.0-flash-001",
    apiKeyPlaceholder: "sk-or-v1-...",
    docsUrl: "https://openrouter.ai/keys",
    showBaseUrl: true,
    needsApiKey: true,
  },

  // Specialist
  {
    id: "groq",
    name: "Groq",
    group: "specialist",
    logo: "/logos/groq.svg",
    defaultBaseUrl: "https://api.groq.com/openai/v1",
    defaultModel: "llama-3.3-70b-versatile",
    docsUrl: "https://console.groq.com/keys",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "deepseek",
    name: "DeepSeek",
    group: "specialist",
    logo: "/logos/deepseek.svg",
    defaultBaseUrl: "https://api.deepseek.com/v1",
    defaultModel: "deepseek-chat",
    docsUrl: "https://platform.deepseek.com/api_keys",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "mistral",
    name: "Mistral AI",
    group: "specialist",
    logo: "/logos/mistral.svg",
    defaultBaseUrl: "https://api.mistral.ai/v1",
    defaultModel: "mistral-large-latest",
    docsUrl: "https://console.mistral.ai/api-keys",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "together",
    name: "Together AI",
    group: "specialist",
    logo: "/logos/together.svg",
    defaultBaseUrl: "https://api.together.xyz/v1",
    defaultModel: "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    docsUrl: "https://api.together.ai/settings/api-keys",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "xai",
    name: "xAI (Grok)",
    group: "specialist",
    logo: "/logos/xai.svg",
    defaultBaseUrl: "https://api.x.ai/v1",
    defaultModel: "grok-2-vision",
    docsUrl: "https://console.x.ai",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "minimax",
    name: "MiniMax",
    group: "specialist",
    logo: "/logos/minimax.svg",
    defaultBaseUrl: "https://api.minimax.io/v1",
    defaultModel: "MiniMax-M3",
    docsUrl: "https://platform.minimax.io",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "glm",
    name: "GLM (Zhipu / Z.AI)",
    group: "specialist",
    logo: "/logos/glm.svg",
    defaultBaseUrl: "https://open.bigmodel.cn/api/paas/v4/",
    defaultModel: "glm-4v",
    docsUrl: "https://open.bigmodel.cn",
    showBaseUrl: true,
    needsApiKey: true,
  },
  {
    id: "mimo",
    name: "MiMo (Xiaomi)",
    group: "specialist",
    logo: "/logos/xiaomi.svg",
    defaultBaseUrl: "https://api.xiaomimimo.com/v1",
    defaultModel: "MiMo-V2.5",
    docsUrl: "https://mimo.mi.com",
    showBaseUrl: true,
    needsApiKey: true,
  },

  // A reader, not a model: the credential imports a recipe from a URL
  // through, and the connection test reads one page instead of listing
  // models. No base URL to configure — the endpoint is the service — and
  // no model to name either.
  {
    id: "jina",
    name: "Jina Reader",
    group: "specialist",
    defaultBaseUrl: "",
    // A value, like the three key prefixes above it — the reader's keys
    // start with their own prefix, and an OpenRouter shape here would
    // describe a key this service never issued.
    apiKeyPlaceholder: "jina_…",
    docsUrl: "https://jina.ai/reader",
    showBaseUrl: false,
    hasModel: false,
    needsApiKey: true,
  },

  // Local
  {
    id: "ollama",
    name: "Ollama",
    group: "local",
    icon: "Server",
    defaultBaseUrl: "http://host.docker.internal:11434/v1",
    defaultModel: "llama3.2",
    showBaseUrl: true,
    needsApiKey: false,
  },
  {
    id: "lm_studio",
    name: "LM Studio",
    group: "local",
    icon: "Server",
    defaultBaseUrl: "http://host.docker.internal:1234/v1",
    defaultModel: "local-model",
    showBaseUrl: true,
    needsApiKey: false,
  },
  {
    id: "vllm",
    name: "vLLM / llama.cpp",
    group: "local",
    icon: "Server",
    defaultBaseUrl: "http://host.docker.internal:8000/v1",
    showBaseUrl: true,
    needsApiKey: false,
  },

  // Custom
  {
    id: "custom",
    name: "Custom OpenAI-compatible",
    // Not a brand, so it is not the same string in five languages.
    nameKey: "config.providerName.custom",
    group: "custom",
    icon: "Settings",
    defaultBaseUrl: "",
    // A value, like the three key prefixes above it — this entry is
    // OpenAI-compatible by definition, so that is the shape its key has.
    // It read "API Key": a label sitting where the rest of the list shows
    // examples, in English, on a translated screen.
    apiKeyPlaceholder: "sk-...",
    showBaseUrl: true,
    needsApiKey: true,
  },
];

export const getProviderDescriptor = (
  id: LlmProvider,
): ProviderDescriptor | undefined => PROVIDERS.find((p) => p.id === id);

/**
 * Returns the capabilities a connection of this provider should declare by
 * default. The user can widen (e.g. add vision to a custom text-only model)
 * but not narrow below this baseline. Used by the form on provider change.
 */
/**
 * What to tick for a provider before anybody says otherwise — a starting
 * point, never a verdict.
 *
 * This used to be called `providerDefaultCapabilities`, and the form treated
 * it as the name promised: a capability on this list was drawn as a fixed
 * badge with a tick, with no way to remove it. But a protocol is not a model.
 * A connection to `deepseek-v4-flash` through an OpenAI-compatible endpoint
 * inherited VISION from the shape of the API, showed it as a fact, and could
 * not be told that the model does not read images — so it stayed on the list
 * of candidates for reading photographs.
 *
 * Whether a model can actually do the job is a question with an answer: the
 * connection test asks it. See `capability_checks` on the connection.
 */
export const providerDefaultCapabilities = (
  provider: LlmProvider,
): LlmCapability[] => {
  // The reader is not a model at all: its capability is the page fetch
  // itself, and ticking vision or text on it would put it in purpose
  // pickers where it cannot serve.
  if (provider === "jina") return ["url_fetch"];
  const descriptor = getProviderDescriptor(provider);
  if (!descriptor) return ["text"];
  // Cloud providers whose flagship models read images start with both ticked;
  // local/custom start conservative (text-only).
  const visionCapable: ReadonlySet<LlmProvider> = new Set([
    "openai",
    "anthropic",
    "google",
    "openrouter",
    "xai",
    "minimax",
    "glm",
    "mimo",
  ]);
  return visionCapable.has(provider) ? ["vision", "text"] : ["text"];
};

export const CAPABILITIES: ReadonlyArray<{
  value: LlmCapability;
  labelKey: string;
}> = [
  { value: "vision", labelKey: "config.capability.vision" },
  { value: "text", labelKey: "config.capability.text" },
  { value: "url_fetch", labelKey: "config.capability.url_fetch" },
];

/**
 * What choosing a provider fills in — the whole of it, in one place.
 *
 * The dialog used to apply these from the provider-change handler and from
 * nowhere else, so a dialog that *opened* on a provider opened with its two
 * required fields empty. The shortest path through the form — accept the
 * provider already selected, type the key, save — was the one path that
 * could not work, and the reader learned it from the backend: "AI connection
 * base URL must use http or https".
 */
export const providerDefaults = (
  provider: LlmProvider,
): {
  api_base_url: string | null;
  model_name: string | null;
  capabilities: LlmCapability[];
} => {
  const descriptor = getProviderDescriptor(provider);
  return {
    api_base_url: descriptor?.defaultBaseUrl || null,
    model_name: descriptor?.defaultModel ?? null,
    capabilities: providerDefaultCapabilities(provider),
  };
};
