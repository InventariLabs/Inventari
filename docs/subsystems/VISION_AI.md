# Vision AI & Product Recognition

- **Endpoint**: `POST /api/v1/vision/extract`
- **Provider**: any of the sixteen model providers the AI Connections screen offers — OpenRouter, OpenAI,
  Anthropic, Google Gemini, Groq, DeepSeek, Mistral AI, Together AI, xAI, MiniMax, GLM, MiMo, Ollama,
  LM Studio, vLLM / llama.cpp, or any other OpenAI-compatible endpoint (`custom`). The connection must
  declare the `vision` capability; what each provider enforces on the wire is in [LLM.md](LLM.md#provider-support).

## Configuration
- **Global**: `.env` (`LLM_API_KEY`, `LLM_PROVIDER`, `LLM_API_BASE_URL`, `LLM_MODEL`, `LLM_CAPABILITIES` — vision needs `vision` declared; see [LLM.md](LLM.md#the-environments-model)).
- **Per-Tenant**: AI connections (API key encrypted) in the `ai_connections` table, bound to the
  `vision.extract` purpose in `organizations.settings` (Settings → AI Connections).

## Where the work is split

The generic half lives in Core, as `core_api.llm.extract_from_images_async`: quota,
connection resolution for an AI purpose, the prompt shape rendered from the
caller's Pydantic model, one retry when the answer does not fit, one usage row
per attempt. **It contains no domain field name**, and the same code path
serves a food label (expiry date), an equipment nameplate (serial number) and
a library's copyright page (ISBN).

The vision module supplies the question — *this is a photograph of a label;
read what is printed* — and `VisionExtractResult`, which holds identity only:
name, brand, category, barcode, weight/volume, expiry and production dates.

## Modules contribute their own fields

A module that wants more read off the same photograph registers a field group
through `vision_api` (see `app/modules/nutrition/vision_fields.py`):

```python
vision_api.register_label_fields(
    module='nutrition',
    schema=NutritionFacts,          # owned by the contributing module
    instructions='Only when a nutrition table is legible…',
    context_tags=frozenset({PRODUCT_CONTEXT}),
)
```

Two gates decide whether a group rides along, for two different reasons:

- **the module gate** — a switched-off module spends no tokens;
- **the intent gate** — `context_tag`, the purpose the scanned label was
  printed for. A sticker printed for assets never sends a nutrition-table
  question, so the prompt for a rating plate does not mention food at all.

Contributed values come back namespaced under `extra.<module>`, the way module
data sits under its own key in `meta_data`. A group whose module is off leaves
its key absent rather than a row of nulls.

Adding a vertical is one schema plus one registration in that module — no diff
in Core, and none in vision.

## Features
- Extracts: Name, Brand, Category, Barcode, Quantity (Net Weight), Expiry Date, Production Date.
- Nutrition table: `POST /api/v1/vision/extract-nutrition` reads the nutrition
  module's group off a single photograph. The endpoint only names the module
  whose group to read; the shape belongs to `nutrition`. It reads a
  photograph like `/vision/extract` does and sits behind the same permission,
  `vision:extract`.

## A barcode read off a photograph is resolved like a scanned one

Scanning a barcode has always run it past the registered scan providers, one
of which — `OFFScanProvider` — looks it up in the local product database.
Reading the *same* barcode off a photograph did not, so the two ways of
pointing a camera at one package gave different answers: the scan filled in
the manufacturer's data and the photo did not.

`/vision/extract` now hands a legible barcode to `scan_registry.scan` and
returns whatever template a provider produced under `resolved`. A resolver
declares which identifiers it handles (`can_handle`) and is not called for the
rest — the registry has always worked that way, so a module adding a resolver
for its own identifier type adds a provider, not a branch in vision.

The merge rule on the form: a catalogue name and brand beat a reading of a
photograph, everything the catalogue cannot know (the expiry date on the
carton in this person's hand) stays as read. Failure is silence — an
unrecognised code, an unavailable source, a provider that raises — because
enrichment that can block a save is worse than no enrichment.

**Data egress:** none. `OFFScanProvider` reads a local Open Food Facts table
imported from the parquet dump (`app/modules/nutrition/services.py` →
`OFFProductLocal`); no barcode and no organization data leaves the
installation. A resolver that *does* call an external service must document
what it sends before it ships.

## What is deliberately absent

`storage_type` (`'FREEZER'` / `'FRIDGE'` / `'PANTRY'`, defaulting to a pantry)
used to steer the prompt with sentences about frozen meat and dairy. A shelf's
temperature is one vertical's furniture; intent now travels as the label's
`context_tag`, which is a fact about the sticker rather than a guess about the
room.

## Outbound request safety

`AiConnection.api_base_url` is user-supplied — the Test-connection endpoint
accepts it inline, before anything is saved — so every LLM call runs through
the same SSRF guard as webhooks (`app/core/llm/_outbound.py` →
`app/core/ssrf_guard.py`):

- private, loopback and link-local targets are **blocked**, both as IP
  literals and as hostnames that resolve into those ranges;
- a hostname that does not resolve is rejected rather than waved through;
- the resolved address is **pinned**: the request goes to that IP with the
  hostname carried in the `Host` header and in TLS SNI, so a name cannot
  answer public at validation time and private at request time.

`LLM_ALLOW_PRIVATE_NETWORKS` (default `false`) opts out. Set it to `true` on
self-hosted installs that run a local model server — Ollama on
`127.0.0.1:11434`, LM Studio, vLLM — which are private targets by nature.
It is the LLM-side counterpart of `WEBHOOKS_ALLOW_PRIVATE_NETWORKS` and is
deliberately a separate switch: allowing a local model server should not
also allow webhook deliveries into the internal network.

## Running a local model

Ollama, LM Studio and vLLM are listed as providers, and the path to them has
three steps that no amount of reading the provider list makes obvious. All
three are one-time.

**1. The address is the host, not the container.** The backend runs in a
container, so `http://localhost:11434` points at the container itself. Use
`http://host.docker.internal:11434/v1` — which is what the provider picker
already fills in — and note that `docker-compose.yml` gives the backend
`extra_hosts: host.docker.internal:host-gateway`, so the name resolves on
Linux too, where Docker does not provide it by default.

**2. That address is refused until you allow private targets.** Every LLM call
goes through the SSRF guard described above, and a local model server is a
private target by definition. Saving the connection fails with a message that
names the switch; set it and restart the backend:

```
LLM_ALLOW_PRIVATE_NETWORKS=true
```

This is the one place where the application hands you a default it will then
reject, and it is deliberate: the guard defaults to closed, and opening it is
an operator's decision rather than a form's.

**3. Raise the context window before you judge any model.** Ollama serves every
model with `num_ctx = 4096` unless told otherwise, whatever the model itself
supports — `qwen3-vl` declares 262 144 and still gets 4096. A photograph at
1024 px is about 1 400 prompt tokens, so a model that thinks before it answers
runs out of room and the reply arrives empty or truncated. It looks exactly
like a model that cannot read labels:

```
LLM answer is empty from <connection>/<model>: finish_reason='length'
  usage={'prompt_tokens': 1378, 'completion_tokens': 2718, 'total_tokens': 4096}
```

That `total_tokens: 4096` is the tell — it is the window, not the request's
`max_tokens`, which the application sets to 8000. Raise it for the daemon:

```
sudo systemctl edit ollama      # Environment="OLLAMA_CONTEXT_LENGTH=8192"
sudo systemctl restart ollama
```

or per model, which is how the measurements below were taken:

```
curl http://localhost:11434/api/create -d \
  '{"model":"qwen3-vl-ctx8k","from":"qwen3-vl:8b","parameters":{"num_ctx":8192}}'
```

It is not free. A bigger window is slower, and the HTTP timeout for a model
call is bounded (`request_timeout` in `app/core/llm/timeouts.py`: 60 s for a
hosted provider, `LLM_LOCAL_REQUEST_TIMEOUT_SECONDS`, 300 s by default, for
Ollama, LM Studio and vLLM) — except on the `google` provider, whose native
SDK client is built without a timeout and so has no limit at all (see *How
long a call may take* in `LLM.md`). The measurements below were taken when every
provider had a fixed 60 s, which is the timeout their rows name. On modest
hardware raising the window trades truncated answers for
`LlmTransportError: ReadTimeout` — which reads like a network fault and is not
one. Model weights are pulled outside the application (`ollama pull
qwen2.5vl:7b`), and `qwen3-vl` additionally needs Ollama 0.12.7 or newer; an
older daemon reports it as a missing model, which reads like a typo rather
than a version floor.

## Which model — measured on photographs, 2026-09-05

The connection test's contract probe draws its own label: black text, white
ground, no perspective, no glare. It answers "can this model return the agreed
shape", which is the right question for a settings screen and the wrong one
for a recommendation — on that label a 0.75B model scores what a 7B model
scores. So the models below were walked through **fourteen real product
photographs** instead.

The corpus is Open Food Facts front images, addressed by barcode and fetched
at run time (`backend/scripts/vision_matrix_corpus.json`), so nothing binary
lives in this repository and the measurement can be repeated:

```
docker compose exec backend uv run python scripts/vision_model_matrix.py \
    --org <uuid> --models <a,b,c> --out /tmp/matrix.json
```

They are photographs, not product shots: held in hands, at angles, on a rubber
mat, on a red tablecloth, in Turkish, French, Spanish, Portuguese and Italian.
Every call goes through `VisionService.extract_from_bytes_list`, so the schema,
the prompt, the retry and the usage rows are production's, and each image is
shrunk to 1024 px at quality 80 first — what `compressImage` in the browser
sends.

**Three columns, because reading, reciting and misfiling look identical in
one.** These are famous products, so a model that has memorised Nutella will
happily supply a net weight that is nowhere in the frame:

- **read** — fields legible on the photograph that the model got right. Ten of
  the fourteen fronts show no weight at all and none shows a best-before date,
  so the denominator is 32, not 56.
- **invented** — fields *not* legible that the model answered anyway. This is
  the column that matters most for an inventory: a fabricated number arrives
  with the same confidence as a read one, and unlike a blank it never shows up
  on a list of things to fix.
- **misfiled** — an answer genuinely printed on the package but belonging to a
  different field. The `21,5 g` on a Kinder Bueno wrapper is the per-bar
  nutrition reference, not the net weight; a model answering it read the
  picture and filed it in the wrong drawer, which is a different mistake from
  making it up.

### What the corpus changed about the request

A ranking tells someone which model to buy. It does not help the person who
has already chosen one, and the tables below say that four of the eight local
models fabricate a net weight. So the same corpus was pointed at the
application instead.

Every fabrication in the whole run — eighteen of them — was in one field,
`weight`. None was in the name, the brand or the date, and **none at all was in
the ten nutrition fields**, which the same models were asked for in the same
requests. The difference was in how they were asked:

```
nutrition (contributed): "...if it is not visible, leave the values null
                          rather than estimating."
weight    (core, before): "net weight or volume exactly as printed, with its
                          unit; look in the package's bottom corners"
```

One says silence is the right answer; the other says keep looking. The shared
instructions said "do not infer anything that is not legible", which is a
prohibition and not the same thing as permission.

Rewording the field description alone — naming the three values that actually
turned up as fake weights, and saying null is allowed — measured as:

| model | before | after |
|---|---|---|
| `qwen2.5vl:7b` | 29/32 read, **7 fabricated** | **30/32 read, 0 fabricated** |
| `google/gemini-3.5-flash-lite` | 32/32, 0 | 32/32, 0 |
| `qwen3-vl:8b` | 28/32, 1 | 26/32, 1 |
| `minicpm-v4.6:1b` | 23/32, 3 | 21/32, 1 |
| `mistralai/mistral-small-2603` | 22–30/32, 7–8 | 21–24/32, 7–9 |

Two things are worth taking from that table rather than the numbers.

**Dose matters more than direction.** Stronger versions — the same rule added
to the shared instructions, and a sentence noting that most fields would be
null anyway — cut fabrication further and took reading down with it:
`mistral-small` fell to 8–20 of 32, answering null for "Coca-Cola" and
"nutella" printed across half the pack, and the control lost a field. Four
formulations were measured; the one that ships is the only one where no model
came out worse than it went in.

**It does not fix a model that recites.** `mistral-small` fabricates at the
same rate under every wording tried, and the wordings strong enough to stop it
cost it a third of its reading. That is a reason not to recommend it, not a
reason to keep rewriting the prompt.

The measurement is repeatable: the harness takes `--connection` so a second
provider can be measured without disturbing the first, and `--rescore` re-applies
a corrected corpus to answers already collected, so fixing the ground truth
never costs the calls again.

### The runs behind these tables

The hosted table and the second local table below are the harness's own
output, and the run each came from is in the repository —
`docs/subsystems/vision-matrix/` holds one JSON per pass, with every
photograph, every field as the model answered it, the provider's own text for
each failure, and the tokens and cost that call spent. That is where the
per-field detail lives; those tables are a summary of it. The other
measurements here (the first local pass, the wording comparison, the
context-window and reasoning comparisons, the connection-test results) come
from runs that are not archived.

| file | what it is |
|---|---|
| `2026-09-05-hosted-openrouter-pass-1.json` | ten hosted models, first pass — no token or cost columns, because the run predates the usage attribution the harness now makes |
| `2026-09-05-hosted-openrouter-pass-2.json` | the same ten, second pass — the hosted table below |
| `2026-09-05-hosted-muse-glimmer-pass-3.json`, `…-pass-4.json` | two further passes of one id, kept because they are the evidence for the routing section |
| `2026-09-06-local-ollama.json` | the eight local models, on the field description that ships |

Rendering one back into its table costs nothing and reaches no provider — the
file goes in on standard input, because the container has the code and the
host has the file:

```bash
docker compose exec -T backend uv run python scripts/vision_model_matrix.py \
    --report /dev/stdin < docs/subsystems/vision-matrix/2026-09-05-hosted-openrouter-pass-2.json
```

**The tables that follow were measured before this change**, on the wording in
the left-hand column above. They still rank the models correctly — the change
moves fabrication, not reading — but a model's `invented` count is the old one.
The one exception is the local pass repeated a day later, which is measured on
the shipped wording and is marked as such; there `qwen2.5vl` fabricates one
weight rather than none, so read the right-hand column above as "about none"
and not as a zero.

### What the connection test says about the same models

Every model in the table below was also put through
`POST /api/v1/ai-connections/test`, which runs the drawn label. All nine that
answered returned `verdict: ok` — including the one that reads 9 of 32 fields
off photographs and the one that fabricates eight weights. The verdict is not
wrong: it asks whether the answer fits the contract, and it did. It simply
cannot rank.

The reading report beside it cannot either, and worse, it is misleading in the
other direction. Six of the nine reported 2 of 4 fields as the probe scored
them that day, with the same two misses, `name` and `brand`. What Gemini 3.5
Flash Lite actually returned:

```
name         expected 'OAT DRINK'        read 'OAT DRINK Barista Edition'
brand        expected 'Barista Edition'  read None
weight       expected '1 L'              read '1 L'
expiry_date  expected '2027-01-31'       read '2027-01-31'
```

The model read the picture correctly. Nothing on that label marks which line is
the brand — "Barista Edition" is a variant name, not a manufacturer — so
answering "the name is OAT DRINK Barista Edition and I see no brand" is the
better reading of the two. The probe asserted a brand its own drawing did not
establish, and compared names by exact equality. `mistral-small-2603` goes
further and returns nothing at all on the drawn label while reading 28 of 32
fields off photographs.

Both of those measurements describe the probe as it stood that day; both
have since been fixed. The brand left the scored set (nothing on the drawn
label establishes a maker), and the name comparison now accepts a reading
fuller than the expected line while refusing one that stops short of it
('OAT' for 'OAT DRINK' is a fragment, not a reading) — the counts of "2 of
4" above belong to the four-field report, and the report scores three fields
today.

Two conclusions, and the second is the reason this file has a table in it:
the settings screen's reading column understates good models — a known
limitation of the probe's scoring, not of the models — and **a synthetic
label cannot choose a model for you.**

#### The same probe, on the eight local models

The hosted paragraph above covers the nine ids that answered through
OpenRouter. The eight local models went through the same endpoint, with the
draft body the settings screen sends (`provider: ollama`, the base URL, the
model name, `capabilities: ["vision"]`), on an otherwise idle machine:

| model | what the probe said |
|---|---|
| `granite3.2-vision-ctx8k` | `verdict: ok`, 2 of 4 fields as the probe scored them that day — both times it was asked |
| `qwen2.5vl-ctx8k` | `verdict: ok`, then 400 `ReadTimeout` minutes later |
| `gemma3-ctx8k` | `verdict: ok`, then 400 `ReadTimeout` minutes later |
| `minicpm-v-ctx8k` | `verdict: ok`, then 200 `contract_failed` |
| `qwen3-vl-ctx8k` | 400 `ReadTimeout`, then `verdict: ok` on an immediate retry |
| `minicpm-v4.6-ctx8k` | 400 `ReadTimeout` |
| `glm-ocr-ctx8k` | 400 `ReadTimeout` |
| `llama3.2-vision-ctx8k` | 400 — Ollama cannot load `mllama` at all, as it also refuses when asked directly |

**Which of them pass is not stable, and that is the finding.** Every model in
that list reads labels — `gemma3` gets 30 of 32 fields off photographs,
`qwen3-vl` 29 — and six of the eight both passed and failed the same probe.
Naming a model makes Ollama load its weights, evicting whatever was resident,
and the client's fixed sixty seconds covers that load and the answer together.
So the verdict reports how long the first call took as much as it reports the
model, and `qwen3-vl` failing and then passing on an immediate retry is the
clearest single measurement of it.

For somebody installing this, that means a working model can fail its first
Test after being selected, and the message it fails with — "Could not reach
the model provider" — points at the URL and the key rather than at the wait.
That was the wording at the time of this run (today: a call that runs out of
time arrives as `LlmTimeoutError`, whose message names the wait, and local
runtimes get 300 s by default — `app/core/llm/timeouts.py`). A failed first
Test after selecting a model still deserves one retry before the URL or the
key are suspected.

The reading column repeats the hosted lesson in a harsher form. `gemma3`, the
best local reader in the corpus, matched none of the checked fields on the
drawn label in the run where it answered at all; `granite3.2-vision`, which
fabricates six fields (three weights and three expiry dates) across fourteen
photographs, matched two of the four
fields the probe scored that day — a count from the same four-field report the
hosted table carries — and comes back `ok` every time it is asked.

### Hosted models, through OpenRouter

| model | answered | read | invented | misfiled | median | tokens | cost / 14 photos |
|---|---|---|---|---|---|---|---|
| `google/gemini-3.5-flash-lite` | 14/14 | **32/32** | 0 | 0 | **1.4 s** | 30 126 | $0.0123 |
| `google/gemini-3.8-flash` | 14/14 | **32/32** | 0 | 0 | 4.7 s | 34 868 | $0.0467 |
| `deepseek/deepseek-v4-flash-vision-exp` | 14/14 | 31/32 | 0 | 1 | **1.0 s** | 19 464 | $0.0008 |
| `minimax/minimax-m3:free` | 14/14 | 31/32 | 0 | 1 | 2.6 s | 20 926 | free tier |
| `meta-llama/llama-4-scout` | 14/14 | 30/32 | 0 | 1 | 2.9 s | 28 782 | $0.0031 |
| `z-ai/glm-5.3-flash` | 14/14 | 30/32 | 0 | 1 | 13.1 s | 21 089 | $0.0039 |
| `mistralai/mistral-small-2603` | 14/14 | 28/32 | **8** | 1 | 1.4 s | 19 455 | $0.0035 |
| `meta/muse-glimmer-30b` | 14/14 | 9/32 | 0 | 0 | 2.4 s | 18 520 | $0.0049 |
| `qwen/qwen3.8-flash` | 0/14 | — | — | — | — | — | refused, see below |
| `qwen/qwen3.7-flash` | 0/14 | — | — | — | — | — | refused, see below |

**Recommended: `google/gemini-3.5-flash-lite`.** It read every legible field on
every photograph, twice, invented nothing, and answered in under two seconds.
Its two passes were identical — see the note on routing below, which
explains why that is not a coincidence.

`deepseek-v4-flash-vision-exp` is the value pick and fifteen times cheaper, but
its single miss is the wrong kind: it read `1,5L` off a bottle labelled
`1,15 L`, identically in both passes. A dropped digit inside a number survives
every sanity check a blank field would fail. Its `exp` suffix is also a warning
— experimental ids get retired, and a saved connection pointing at one stops
working without notice.

`mistral-small-2603` is the cautionary entry. It reads about as well as the
rest, and on eight of the ten photographs with no visible weight it supplied
one anyway: `350g` for the Nesquik, `200g` for the LU Prince, `190g` for the
Barilla pesto — that last one is the product's real weight, which is exactly
the point. It is reciting a catalogue, not reading a label.

### The same model id is not the same model

Every OpenRouter id resolves to a pool of upstream hosts, and two passes can
land on different ones. `meta/muse-glimmer-30b` scored 26/32, then 9/32, 10/32
and 9/32 on four identical passes. On the second pass, compared field by field
against the first, it returned `name: null` for every single photograph while
still reading the brand on half of them; the two later scores are consistent
with the same shape. Its id serves four different companies, only one of which
declares what quantisation it runs.

The correlation across the table is hard to miss:

| id | upstream hosts | pass-to-pass |
|---|---|---|
| `google/gemini-3.5-flash-lite` | 8, all Google | 32/32, 32/32 |
| `deepseek/deepseek-v4-flash-vision-exp` | 6 different companies | 31/32, 31/32 |
| `z-ai/glm-5.3-flash` | 23 different companies | 31/32, 30/32 |
| `meta/muse-glimmer-30b` | 4 different companies | 26/32 … 9/32 |

A single-vendor pool behaves like one model. A community pool is a distribution,
and a matrix measured once on such an id says less than it looks like it says.
Going direct to the provider (`provider: google` with an AI Studio key) removes
the routing entirely, at the same per-token price — Google lists $0.30 / $2.50
per million, which is what OpenRouter charges. Google also has a free tier for
this model, whose terms say free-tier content is used to improve their
products; for an application people self-host to keep their data at home, that
is a decision rather than a footnote.

Two things about that route are worth saying plainly, because the table does
not cover them: **every measurement here went through OpenRouter**, and the
native `google` provider is a different client in this codebase, unmeasured.
On that client `disable_reasoning` maps to a zero-budget `thinking_config` —
the flash family honors it, Pro ignores a zero budget (its floor is 128) and
keeps thinking, so the token budget is still the only defence there.

### Local models, through Ollama

All measured with `num_ctx = 8192` — at Ollama's default of 4096 the bottom
two rows lose a third of their answers, see below. Same hardware throughout: a
Radeon RX 6800 (16 GB, ROCm) with the weights resident in VRAM, on a machine
that was running other work, so read the timings as an order of magnitude and
the counts as the finding.

**"fields read" is out of 32 for everyone**, including the photographs a model
declined to answer. The separate "accuracy" column is out of what it did
answer, and the gap between the two columns is the model's silence.

| model | size | answered | fields read | accuracy | invented | median |
|---|---|---|---|---|---|---|
| `qwen3-vl:8b` | 5.9 GB | 13/14 | **28/32** | 28/30 | 1 | 19.3 s |
| `qwen2.5vl:7b` | 5.7 GB | **14/14** | **29/32** | 29/32 | **7** | **2.7 s** |
| `gemma3:12b` | 7.8 GB | 12/14 | 27/32 | **27/27** | 1 | 23.3 s |
| `llama3.2-vision:11b` | 7.5 GB | 12/14 | 27/32 | **27/27** | 1 | 22.5 s |
| `minicpm-v4.6:1b` | 1.6 GB | 12/14 | 26/32 | 26/28 | 5 | 16.4 s |
| `minicpm-v:8b` | 5.2 GB | 11/14 | 25/32 | **25/25** | 1 | 18.0 s |
| `granite3.2-vision:2b` | 2.3 GB | 10/14 | 23/32 | **23/23** | 1 | 21.9 s |
| `glm-ocr` | 2.1 GB | 11/14 | 21/32 | 21/26 | 2 | 33.5 s |

**Recommended, on this run's field description: `qwen3-vl:8b`.** (The repeat
on the wording that ships, in the next table, puts `gemma3` level with it —
read both before choosing.) It reads more of the corpus than anything else
that stays honest, and it invented one field where `qwen2.5vl:7b` invented
seven. Needs Ollama 0.12.7 or newer.

`qwen2.5vl:7b` is the one to pick when twenty seconds a photograph is not
acceptable — it is seven times faster, answered every photograph, and reads
the most fields of any local model. It also supplied a net weight on seven of
the ten fronts that do not show one. For a shelf inventory that is the trade
being made, and it should be made deliberately.

The 11-12B models converge on a shape worth naming: `gemma3:12b`,
`llama3.2-vision:11b` and `minicpm-v:8b` were **never wrong about a field they
answered** — 27/27, 27/27, 25/25 — and each simply declined two to three
photographs. A model that says nothing rather than something wrong is the
easier failure to build a workflow around.

`glm-ocr` earns its last place for an instructive reason: it reads text
extremely well and is not an instruction-following model. It returns the page,
not the schema, and the retry costs it a hundred thousand tokens per pass:

```
LlmContractError: LLM did not return JSON. Answer began:
  'Nestle\nNesquik\n\nOUVEAU\nOpti-Déj™\nVit D Fer Zinc\nComplète les'
```

**This reverses the recommendation this file carried before.** On the drawn
label `qwen2.5vl:7b` looked like the clear pick and `qwen3-vl:8b` looked
broken — it was being truncated by a context window, not failing to read.
Fourteen photographs and a bigger window put them the other way round, which
is the whole argument for measuring on photographs.

#### The same eight, a day later, on the wording that ships

The table above was measured on the field description this release replaces.
Repeating the whole local pass on the shipped wording, with the harness
exactly as it stands in the repository, gives the table below — the tags are
the local `num_ctx 8192` variants, which is what the models were served as
both times:

| model | answered | read | accuracy | invented | misfiled | median | tokens |
|---|---|---|---|---|---|---|---|
| `gemma3-ctx8k` | 14/14 | 30/32 | 30/32 | **0** | 1 | 3.8 s | 10 941 |
| `qwen2.5vl-ctx8k` | 14/14 | 29/32 | 29/32 | **1** | 2 | 5.3 s | 21 944 |
| `qwen3-vl-ctx8k` | 14/14 | 29/32 | 29/32 | 1 | 1 | 25.8 s | 41 727 |
| `minicpm-v-ctx8k` | 13/14 | 26/32 | 26/29 | 0 | 0 | 2.1 s | 11 825 |
| `minicpm-v4.6-ctx8k` | 12/14 | 25/32 | 25/27 | 3 | 0 | 12.8 s | 53 939 |
| `granite3.2-vision-ctx8k` | 14/14 | 24/32 | 24/32 | **6** | 0 | 5.9 s | 90 440 |
| `glm-ocr-ctx8k` | 9/14 | 16/32 | 16/19 | 1 | 0 | 35.9 s | 139 264 |
| `llama3.2-vision-ctx8k` | 0/14 | 0/32 | 0/0 | 0 | 0 | 0.6 s | 0 |

Raw file: `docs/subsystems/vision-matrix/2026-09-06-local-ollama.json`. The
columns are the harness's own, minus `supplied` and `cost` — nothing is
contributed and nothing is billed on a local model, so both read zero for
every row.

Three things in it are worth carrying out of the numbers.

**The prompt change holds, and "none" was one pass.** `qwen2.5vl` fabricated
seven weights on the old wording and one here: `500g` on the Nesquik front,
which shows none. The direction is the finding; a single
fabrication either way is inside the run-to-run spread, so read the change as
"seven to about none" rather than as a zero.

**A model can leave without warning.** `llama3.2-vision` answered nothing at
all, on every photograph, and not for a reason of its own: Ollama 0.32.5 no
longer knows the `mllama` architecture and the server exits while loading it
(`unknown model architecture: 'mllama'`). The same tag read 27 of 32 fields
the day before. Nothing in the application changed — a local
runtime upgrade retired a model, which is a failure mode a hosted id does not
have and a self-hosted installation should expect.

**The timings above are the honest ones.** The first pass ran on a machine
doing other work and the medians carry it — `gemma3` reads 23.3 s there and
3.8 s here for the same fourteen photographs. The counts are comparable across
the two passes; the seconds are not.

The two remaining shifts are ordinary sampling: `granite3.2-vision` invented
six fields here (three weights and three expiry dates) against one before, `glm-ocr` answered nine photographs
instead of eleven. Both are models the file does not recommend, and both moved
by less than the pass-to-pass spread already documented for a hosted id.

#### What the context window is worth

The same four models, at Ollama's default window and at 8192:

| model | 4096 | 8192 |
|---|---|---|
| `qwen2.5vl:7b` | 29/32 | 29/32 |
| `qwen3-vl:8b` | 29/32 | 28/32 |
| `minicpm-v4.6:1b` | 18/32 | **26/32** |
| `glm-ocr` | 16/32 | **21/32** |

It costs nothing for a model that answers briefly and is worth a third of the
corpus to a model that thinks or transcribes at length. Failures do not vanish,
they change shape: `qwen3-vl` stopped being truncated and started timing out at
60 s instead.

Failures across the whole run are a property of the model, not of any one
photograph — the worst photograph broke 4 of 20 attempts, the best three broke
none, and nothing in between stands out.

### Failures, and what the provider actually said

`qwen/qwen3.8-flash` and `qwen/qwen3.7-flash` answered nothing at all — not a
model problem, an account setting, and one worth recognising because the
message does not say so:

```
404 {"error":{"message":"All providers have been ignored. To change your
default ignored providers, visit: https://openrouter.ai/settings/privacy",
"failed_routing_step":"Filter by Ignored Providers"}}
```

OpenRouter accounts can be set to refuse providers that train on prompts. When
every host behind an id is refused, the id 404s as though it did not exist. It
reaches the application as a provider error with the body attached, which is
what makes it diagnosable at all.

Everything else that failed, failed locally, and each class arrives as its own
exception type rather than as a generic 500:

| what happened | how it arrives | seen on |
|---|---|---|
| provider stopped at the token limit, nothing written | `LlmEmptyAnswerError`, one call, no retry | `qwen3-vl:8b`, `gemma3:12b` |
| answer arrived but is not the agreed shape | `LlmContractError`, after one retry | `minicpm-v4.6:1b`, `glm-ocr` |
| model still computing when the client timeout expired (then a fixed 60 s) | `LlmTransportError` (today `LlmTimeoutError`, a subclass) | `qwen3-vl` at `num_ctx 8192` |

The first row is worth reading twice, because one message distinguishes two
things that look identical from outside:

```
LLM answer is empty from <connection>/<model>:    finish_reason='length' ... total_tokens=4096 raw_length=0
LLM answer was cut off from <connection>/<model>: finish_reason='length' ... total_tokens=4096 raw_length=7603
```

Same window, same finish reason, opposite diagnosis. The first model wrote
nothing because it spent the window thinking; the second wrote 7 603 characters
of prose that were never going to parse. `raw_length` is what separates them —
the client logs it alongside the token counts for exactly this distinction.

The last row is a misnomer worth knowing about: `LlmTransportError` reads as
"could not reach the provider", and the provider was reached and was working —
it just needed longer than the client's fixed sixty seconds. (Today it arrives
as `LlmTimeoutError`, which says so, and the local default is 300 s.)

### Asking a provider to skip the chain of thought is mostly not honoured

The image path asks for `disable_reasoning=True`, which becomes a `reasoning`
field for OpenRouter and a `thinking` field elsewhere. A provider that does not
know the key answers 400, and the client retries once without it. Across
everything measured here, that retry is the normal case, not the exception:

- **OpenRouter rejected it** for both Gemini models, `glm-5.3-flash` and
  `muse-glimmer-30b` — every call, all fourteen photographs.
- **The native Google client sends it as a zero-budget `thinking_config`**
  (since the migration to `google-genai`, which replaced the end-of-lifed
  `google-generativeai` package that had no such field). The flash family
  honors it; Pro keeps thinking anyway — its floor is 128 — so there only the
  token budget defends the answer.
- **Ollama does not suppress reasoning** on the OpenAI-compatible endpoint; the
  chain of thought arrives in a separate field and still spends the window.

Whether the key is accepted is not even a property of the model. The same id
(`minimax/minimax-m3:free`), the same key and the same payload: zero rejections
in fourteen calls on one run, twenty-eight in twenty-eight on another. The id
resolves to twelve hosts and they disagree.

What that costs is measurable. Two models, two passes each, the same fourteen
photographs, with and without the flag:

| | fields read | median |
|---|---|---|
| flag sent (rejected, then retried) | 30/32 | 10.4 – 13.1 s |
| flag not sent | 31/32 | 1.2 – 2.3 s |

Unlike every other table here, this one was **not** produced by the harness as
it stands: `--keep-reasoning` reached the result file but not the call, so the
two arms were varied by hand at the time. That is fixed — the switch is passed
through and a test holds it — so the comparison can now be re-run with
`--keep-reasoning` and its opposite, and the numbers above are what the
one-off measurement gave.

So the flag buys nothing here and cost a wasted round trip per photograph (today
the client remembers a refusal for an hour, so it is paid once an hour per
worker rather than per photograph). It
does **not** follow that reasoning should be left on — that question is still
unanswered, because in the arm meant to disable it, it was never disabled.

## Structured output & the output contract

The Core LLM layer now enforces and repairs the answer's shape — a shared JSON
parser, one retry with parse feedback, and provider-specific structured output.
The full contract, including the per-provider support table and the "what to do
when the model returns garbage" guidance, lives in
[`docs/subsystems/LLM.md`](LLM.md). Vision is one consumer of that layer; the
422 that names the failing connection and model is described there.
