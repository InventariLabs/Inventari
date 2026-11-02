# LLM Output Contract

Every AI feature in Inventari answers through the same Core LLM layer
(`backend/app/core/llm/`). This page describes the contract that layer enforces
between a caller and the model — how the answer's shape is requested, parsed,
retried, and turned into an error the person using the app can act on. It is
the reference for which providers enforce the contract on the wire and which
rely on the prompt and parser instead.

## Clients and protocol dispatch

Three client adapters speak three wire protocols. The factory
(`app/core/llm/factory.py`) picks one by protocol, not by provider:

- `GoogleClient` — the native Gemini SDK, for the `google` provider.
- `AnthropicClient` — the native Messages API, for the `anthropic` provider.
- `OpenAiCompatibleClient` — the chat/completions shape, for every other
  provider (OpenAI, OpenRouter, Groq, DeepSeek, Mistral, Together, xAI,
  MiniMax, GLM, MiMo, Ollama, LM Studio, vLLM, and the `custom` escape hatch).

The provider → protocol mapping is a single source of truth in
`app/core/llm/enums.py` (`protocol_for`); an unknown provider defaults to the
OpenAI-compatible shape, the de-facto standard.

## The output-contract pipeline

A caller declares the shape it wants and asks the layer to read it back:

1. **Declare the shape.** The caller passes a `LlmRequest` with a
   `json_schema` (often a Pydantic model's `model_json_schema()`) plus the
   prompt, images, and optional sampling overrides.
2. **Enforce it where the provider can.** The client turns `json_schema` into
   the provider's native mechanism (see the table below). The generic image
   path also renders the schema into the prompt with `build_shape_prompt`, so
   a prompt-only provider is at least told the shape; that is redundant where
   the provider enforces the schema and essential where it does not.
3. **Parse tolerantly.** `extract_json` reads the answer even when it is
   wrapped in a markdown fence, carries raw control characters inside strings,
   or was cut off by the token budget — closing brackets where it can.
4. **Retry with feedback.** `complete_json` makes at most two attempts; when
   parsing or validation fails it re-asks once, appending the failed answer and
   the error. Transport failures (timeouts, provider 5xx) are not retried here.
5. **Validate.** `parse_into` unwraps the model's envelope, validates against
   the Pydantic schema, and raises `LlmContractError` when the answer still
   does not fit.

A contract failure and a transport failure are kept apart on purpose: the
former means "the model answered, unusably", the latter "the provider never
answered". In the vision module the first becomes an HTTP `422` whose message
names the AI connection and model and points to Settings → AI Connections; the
second is a 503.

## Provider support

The table lists the sixteen model `LlmProvider` values and what the client actually
puts on the wire. **Only three of them enforce the schema server-side**; the
other thirteen are prompt-only and ride entirely on the parser and one retry.

| Provider | Value | Protocol | Structured output | Note |
|---|---|---|---|---|
| Anthropic | `anthropic` | Anthropic | `tool-use` | Forced `tool_use` block named `structured_response`; falls back to concatenated text if the model returns no `tool_use`. |
| Google | `google` | Google | `response_schema` | `response_mime_type: application/json` plus `response_schema`; degrades to mime-type only when the SDK rejects the schema. |
| OpenRouter | `openrouter` | OpenAI-compatible | `json_schema` | Full `response_format` with `strict: true`; retries once without it if a model refuses it with a 400. |
| OpenAI | `openai` | OpenAI-compatible | `prompt-only` | No `response_format` is sent for this provider. |
| Groq | `groq` | OpenAI-compatible | `prompt-only` | — |
| DeepSeek | `deepseek` | OpenAI-compatible | `prompt-only` | — |
| Mistral | `mistral` | OpenAI-compatible | `prompt-only` | — |
| Together | `together` | OpenAI-compatible | `prompt-only` | — |
| xAI | `xai` | OpenAI-compatible | `prompt-only` | — |
| MiniMax | `minimax` | OpenAI-compatible | `prompt-only` | — |
| GLM | `glm` | OpenAI-compatible | `prompt-only` | — |
| MiMo | `mimo` | OpenAI-compatible | `prompt-only` | — |
| Ollama | `ollama` | OpenAI-compatible | `prompt-only` | Local runtime. |
| LM Studio | `lm_studio` | OpenAI-compatible | `prompt-only` | Local runtime. |
| vLLM | `vllm` | OpenAI-compatible | `prompt-only` | Local runtime. |
| Custom | `custom` | OpenAI-compatible | `prompt-only` | User-supplied `api_base_url` escape hatch. |

The seventeenth value, `jina`, is not a model: it is the page reader recipe
import fetches through, with no LLM protocol (`protocol_for` answers `None`).

Two nuances worth stating plainly:

- **OpenAI is prompt-only here.** The OpenAI-compatible client sends
  `response_format` only for `openrouter`, not for the `openai` provider, so a
  direct OpenAI connection gets the same prompt-only treatment as Groq or
  DeepSeek.
- **OpenRouter support varies by model.** Some OpenRouter models reject
  `response_format: json_schema` with a 400; the client retries once without
  it and remembers the refusal for an hour, so those models silently become
  prompt-only.

## How long a call may take

Two settings, because the two kinds of provider are not close:

| Setting | Default | Applies to |
|---|---|---|
| `LLM_REQUEST_TIMEOUT_SECONDS` | 60 s | Every hosted provider that `OpenAiCompatibleClient` or `AnthropicClient` serves |
| `LLM_LOCAL_REQUEST_TIMEOUT_SECONDS` | 300 s | `ollama`, `lm_studio`, `vllm` |

Which one applies is decided by the connection's `provider`
(`app/core/llm/timeouts.py`), so a self-hosted install needs no configuration
to get the longer one; an unknown provider value is treated as remote.

**The `google` provider is the exception: neither setting reaches it.**
`GoogleClient` builds the native SDK client without a request timeout, and
the SDK's own default is no limit, so a Gemini call that the provider never
answers waits until the request is cancelled from outside. The SDK's timeout
and transport errors also reach the caller as the SDK raised them, not as
`LlmTransportError` or `LlmTimeoutError` (only 401, 402, 404 and 429
refusals are translated), so the degrade-on-transport-failure paths described
below do not catch them. This is a known gap in the client, not a design: if
your Gemini calls hang, that is why.

**Why the local default is five minutes.** Measured on an RX 6800 (16 GB
VRAM, model resident, one 1024 px photograph): `qwen3-vl:8b` at Ollama's
default 4096-token window answers in about 19 s but truncates, because the
reasoning does not fit the window; the same model at `num_ctx=8192` stops
truncating and took **60.1 s** for one image — one tenth of a second past the
minute that used to be compiled in. A bigger model, a larger photograph or a
card that has to page weights in from RAM all push further. If yours does,
raise `LLM_LOCAL_REQUEST_TIMEOUT_SECONDS`; a cloud endpoint that has been
silent for a minute, on the other hand, is not about to answer, and raising
the other setting mostly buys a longer wait for the same failure.

A call that times out while connecting raises `LlmTransportError`: the
provider was not reached. A read or write that runs out of time raises
`LlmTimeoutError` — a subclass of
`LlmTransportError`, so everything that already degrades on a transport
failure keeps degrading — and the reader is told the model did not answer in
time, not that the provider could not be reached. The two send somebody to
different places: one to an address or a certificate, the other to this
setting or to a smaller model.

`list_models`, which backs the connection test, keeps its own 30 s limit on
the OpenAI-compatible and Anthropic clients (the Google client has none). It
is a catalogue read that no model runs for, and a local server that cannot
list its models in half a minute has a different problem.

An update to an AI connection keeps the stored API key when `api_key` is
omitted or masked. An explicit `null` is refused with a 400 naming the field;
send a string to replace it.

## Connection test

`POST /ai-connections/test` runs one real request through the purpose's own
contract probe and judges the answer with the feature's parser, not just
whether the credentials work. Its verdict is `ok`, `contract_failed`, or
`unchecked` (when no probe exists for the connection's capabilities, or a
page-reader connection has no key to test). A `contract_failed` result includes a preview of what the model actually
returned. The test is billed like any other LLM call.

The `schema_enforced` flag on that result reports whether the probe's request
declared a JSON schema — not which provider enforced it on the wire. The table
above is the authoritative enforcement map.

## The environment's model

An organization that has bound nothing in Settings → AI Connections is served
by a connection built in memory, per call, from the backend's environment
(`_legacy_env_fallback` in `app/core/llm/registry.py`). It is the one key
path that reaches an organization nobody configured — a fresh install, or
the demo, which rebuilds every night — and since the key is never stored in
an organization's row, no organization admin can read or redirect it.

| Variable | Meaning |
|---|---|
| `LLM_API_KEY` | The key of the chosen provider. Empty means no fallback. `OPENROUTER_API_KEY`, its earlier name, is still read when this is empty; when both are set and differ, `LLM_API_KEY` wins and start-up logs a warning. |
| `LLM_PROVIDER` | Any provider with an LLM protocol (`openrouter` by default). |
| `LLM_API_BASE_URL` | That provider's endpoint. |
| `LLM_MODEL` | The model id, as the provider's catalogue spells it. |
| `LLM_CAPABILITIES` | What the model can do: `text`, `vision`. Empty is both for `openrouter` and `text` for any other provider. |

The backend refuses to start on a provider it has no client for, an unknown
capability, or a key whose address is empty or still OpenRouter's while
`LLM_PROVIDER` names another provider. A purpose whose capability is not
declared gets no client — the caller answers "not set up" and a warning names
`LLM_CAPABILITIES` — instead of a text-only model failing on a photograph at
the provider. The purposes list reports the same verdict as `usable`.

The fallback has no ceiling of its own: the organization's
`ai_requests_monthly` applies as for any other connection, and on a public
instance the provider's spending cap is the one that holds whatever the app
does.

## What to do when the model returns garbage

If a scan or extraction fails with a message like "could not read this label",
the app is telling you that the AI connection answered but not in a usable
shape — and it now names the connection and model that failed. Do this:

1. Open **Settings → AI Connections**.
2. Run the **connection test** on the connection you are using. It will say
   `contract_failed` if this model cannot do the job, and show a short preview
   of what it returned.
3. Choose a different model or provider for that connection, or switch the
   feature to a connection that passes the test.
4. Try a clearer photo when the input is an image — a blurry or tilted label
   produces an unusable answer too.

If instead the app says no AI connection has been chosen, pick one in
Settings → AI Connections — nothing is configured yet, and that is a setting
rather than a failure of any model.

## What is deliberately absent

The table describes what the *code enforces*, not what any vendor's model
promises about the content. Whether a model returns the *truth* — a real expiry
date rather than a plausible-looking one in perfectly valid JSON — is a
separate question that an evaluation harness would answer; none ships with this
layer. Contract enforcement is the necessary first step, not the last one.
