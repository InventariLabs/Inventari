# Third-party licences

Every component redistributed with Inventari, with the licence it ships under.
Generated — do not edit by hand. Run it from a checkout that has both
`backend/.venv` and `frontend/node_modules` installed:

```bash
cd backend && uv run python manage.py audit scan-dependencies --write
```

What keeps it true runs on this tree: the `licences-fresh` pre-commit hook
(installed by `make setup-hooks`) runs
`backend/scripts/check_licences_fresh.py` when a manifest, a lockfile, this
report or a bundled asset changes, and `make lint` runs the same check over
the whole tree. `.github/workflows/license-scan.yml` can still regenerate and
diff it, but only when someone starts it by hand — its pull-request trigger
is switched off to save runner minutes, so no CI run stands behind this file.

The backend container has no `npm`, so inside it the command only works with
`--skip-frontend` and the frontend section would come out empty.

Scope is what a deployment actually receives: backend runtime packages
(dev-dependencies excluded), the frontend production bundle, the system
packages inside the backend and backup images, the images the stack pulls,
and the static assets the frontend serves.

## Backend runtime (104 packages)

| Package | Version | Licence | Note |
|---|---|---|---|
| `aioboto3` | 15.5.0 | Apache-2.0 |  |
| `aiobotocore` | 2.25.1 | Apache-2.0 |  |
| `aiofiles` | 25.1.0 | Apache-2.0 |  |
| `aiohappyeyeballs` | 2.7.1 | PSF-2.0 |  |
| `aiohttp` | 3.14.5 | Apache-2.0 AND MIT |  |
| `aioitertools` | 0.13.0 | MIT |  |
| `aiosignal` | 1.4.0 | Apache-2.0 |  |
| `alembic` | 1.20.0 | MIT |  |
| `annotated-doc` | 0.0.5 | MIT |  |
| `annotated-types` | 0.8.0 | MIT |  |
| `anyascii` | 0.3.3 | ISC |  |
| `anyio` | 4.14.2 | MIT |  |
| `asyncpg` | 0.31.0 | Apache-2.0 |  |
| `attrs` | 26.1.0 | MIT |  |
| `babel` | 2.18.0 | BSD |  |
| `bcrypt` | 5.0.0 | Apache-2.0 |  |
| `beautifulsoup4` | 4.15.0 | MIT |  |
| `boto3` | 1.40.61 | Apache-2.0 |  |
| `botocore` | 1.40.61 | Apache-2.0 |  |
| `brotli` | 1.2.1 | MIT |  |
| `certifi` | 2026.10.19 | MPL-2.0 |  |
| `cffi` | 2.1.0 | MIT |  |
| `charset-normalizer` | 3.4.9 | MIT |  |
| `click` | 8.4.2 | BSD-3-Clause |  |
| `cryptography` | 50.0.0 | Apache-2.0 OR BSD-3-Clause |  |
| `cssselect2` | 0.9.0 | BSD |  |
| `Deprecated` | 1.3.1 | MIT |  |
| `distro` | 1.9.0 | Apache-2.0 |  |
| `dnspython` | 2.9.0 | ISC |  |
| `email-validator` | 2.3.0 | Unlicense |  |
| `et_xmlfile` | 2.0.0 | MIT |  |
| `fastapi` | 0.141.1 | MIT |  |
| `fonttools` | 4.63.0 | MIT |  |
| `frozenlist` | 1.8.0 | Apache-2.0 |  |
| `google-auth` | 2.56.2 | Apache-2.0 |  |
| `google-genai` | 2.25.0 | Apache-2.0 |  |
| `greenlet` | 3.5.4 | MIT AND PSF-2.0 |  |
| `gunicorn` | 26.2.0 | MIT |  |
| `h11` | 0.16.0 | MIT |  |
| `httpcore` | 1.0.9 | BSD-3-Clause |  |
| `httptools` | 0.8.0 | MIT |  |
| `httpx` | 0.28.1 | BSD |  |
| `idna` | 3.18 | BSD-3-Clause |  |
| `Jinja2` | 3.1.6 | BSD |  |
| `jmespath` | 1.1.0 | MIT |  |
| `limits` | 5.8.0 | MIT |  |
| `Mako` | 1.4.3 | MIT |  |
| `markdown-it-py` | 4.2.0 | MIT |  |
| `MarkupSafe` | 3.0.3 | BSD-3-Clause |  |
| `mdurl` | 0.1.2 | MIT |  |
| `multidict` | 6.9.1 | Apache-2.0 |  |
| `nh3` | 0.3.7 | MIT |  |
| `numpy` | 2.5.1 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |  |
| `openpyxl` | 3.1.5 | MIT |  |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause |  |
| `pandas` | 3.0.6 | BSD |  |
| `pillow` | 13.0.0 | MIT-CMU |  |
| `propcache` | 0.5.2 | Apache-2.0 |  |
| `psycopg2-binary` | 2.9.13 | LGPL |  |
| `pyarrow` | 25.0.1 | Apache-2.0 |  |
| `pyasn1` | 0.6.5 | BSD-2-Clause |  |
| `pyasn1_modules` | 0.4.2 | BSD |  |
| `pycparser` | 3.0 | BSD-3-Clause |  |
| `pydantic` | 2.13.5 | MIT |  |
| `pydantic-settings` | 2.15.0 | MIT |  |
| `pydantic_core` | 2.46.5 | MIT |  |
| `pydyf` | 0.12.1 | BSD |  |
| `Pygments` | 2.20.0 | BSD-2-Clause |  |
| `PyJWT` | 2.15.0 | MIT |  |
| `pyphen` | 0.17.2 | MPL-1.1 | exception: tri-licensed GPL-2.0+/LGPL-2.1+/MPL-1.1 — we take MPL-1.1, so a naive substring match on "GPL" must not read this as a blocker |
| `python-barcode` | 0.16.1 | MIT |  |
| `python-dateutil` | 2.9.0.post0 | BSD OR Apache-2.0 |  |
| `python-dotenv` | 1.2.3 | BSD-3-Clause |  |
| `python-multipart` | 0.0.32 | Apache-2.0 |  |
| `PyYAML` | 6.0.3 | MIT |  |
| `qrcode` | 8.2 | BSD-3-Clause | exception: ships a bogus "License :: Other/Proprietary License" classifier next to "BSD License"; upstream LICENSE is BSD-3-Clause |
| `redis` | 8.1.0 | MIT |  |
| `requests` | 2.34.2 | Apache-2.0 |  |
| `rich` | 15.0.0 | MIT |  |
| `s3transfer` | 0.14.0 | Apache-2.0 |  |
| `shellingham` | 1.5.4 | ISC |  |
| `six` | 1.17.0 | MIT |  |
| `slowapi` | 0.1.10 | MIT |  |
| `sniffio` | 1.3.1 | MIT OR Apache-2.0 |  |
| `soupsieve` | 2.9.1 | MIT |  |
| `SQLAlchemy` | 2.0.51 | MIT |  |
| `sse-starlette` | 3.4.11 | BSD-3-Clause |  |
| `starlette` | 1.3.1 | BSD-3-Clause |  |
| `tenacity` | 9.1.4 | Apache-2.0 |  |
| `tinycss2` | 1.5.1 | BSD |  |
| `tinyhtml5` | 2.1.0 | MIT |  |
| `typer` | 0.27.2 | MIT |  |
| `typing-inspection` | 0.4.2 | MIT |  |
| `typing_extensions` | 4.16.0 | PSF-2.0 |  |
| `urllib3` | 2.8.0 | MIT |  |
| `uvicorn` | 0.52.1 | BSD-3-Clause |  |
| `uvloop` | 0.22.1 | Apache-2.0 OR MIT |  |
| `watchfiles` | 1.2.0 | MIT |  |
| `weasyprint` | 70.0 | BSD |  |
| `webencodings` | 0.5.1 | BSD |  |
| `websockets` | 16.1.1 | BSD-3-Clause |  |
| `wrapt` | 1.17.3 | BSD |  |
| `yarl` | 1.25.1 | Apache-2.0 |  |
| `zopfli` | 0.4.3 | Apache-2.0 |  |

## Frontend production bundle (304 packages)

| Package | Version | Licence | Note |
|---|---|---|---|
| `@alloc/quick-lru` | 5.3.0 | MIT |  |
| `@babel/runtime` | 7.29.7 | MIT |  |
| `@dnd-kit/accessibility` | 3.1.1 | MIT |  |
| `@dnd-kit/core` | 6.3.1 | MIT |  |
| `@dnd-kit/sortable` | 10.0.0 | MIT |  |
| `@dnd-kit/utilities` | 3.2.2 | MIT |  |
| `@floating-ui/core` | 1.8.0 | MIT |  |
| `@floating-ui/dom` | 1.8.0 | MIT |  |
| `@floating-ui/react-dom` | 2.1.9 | MIT |  |
| `@floating-ui/utils` | 0.2.12 | MIT |  |
| `@jridgewell/gen-mapping` | 0.3.13 | MIT |  |
| `@jridgewell/resolve-uri` | 3.1.2 | MIT |  |
| `@jridgewell/sourcemap-codec` | 1.6.0 | MIT |  |
| `@jridgewell/trace-mapping` | 0.3.31 | MIT |  |
| `@nodelib/fs.scandir` | 2.1.5 | MIT |  |
| `@nodelib/fs.stat` | 2.0.5 | MIT |  |
| `@nodelib/fs.walk` | 1.2.8 | MIT |  |
| `@radix-ui/number` | 1.1.3 | MIT |  |
| `@radix-ui/primitive` | 1.1.7 | MIT |  |
| `@radix-ui/react-alert-dialog` | 1.1.23 | MIT |  |
| `@radix-ui/react-arrow` | 1.1.15 | MIT |  |
| `@radix-ui/react-collection` | 1.1.15 | MIT |  |
| `@radix-ui/react-compose-refs` | 1.1.5 | MIT |  |
| `@radix-ui/react-context` | 1.2.2 | MIT |  |
| `@radix-ui/react-dialog` | 1.1.23 | MIT |  |
| `@radix-ui/react-direction` | 1.1.4 | MIT |  |
| `@radix-ui/react-dismissable-layer` | 1.1.19 | MIT |  |
| `@radix-ui/react-focus-guards` | 1.1.6 | MIT |  |
| `@radix-ui/react-focus-scope` | 1.1.16 | MIT |  |
| `@radix-ui/react-id` | 1.1.4 | MIT |  |
| `@radix-ui/react-popover` | 1.1.23 | MIT |  |
| `@radix-ui/react-popper` | 1.3.7 | MIT |  |
| `@radix-ui/react-portal` | 1.1.17 | MIT |  |
| `@radix-ui/react-presence` | 1.1.10 | MIT |  |
| `@radix-ui/react-primitive` | 2.1.10 | MIT |  |
| `@radix-ui/react-roving-focus` | 1.1.19 | MIT |  |
| `@radix-ui/react-select` | 2.3.7 | MIT |  |
| `@radix-ui/react-slot` | 1.3.3 | MIT |  |
| `@radix-ui/react-tabs` | 1.1.21 | MIT |  |
| `@radix-ui/react-use-callback-ref` | 1.1.4 | MIT |  |
| `@radix-ui/react-use-controllable-state` | 1.2.6 | MIT |  |
| `@radix-ui/react-use-effect-event` | 0.0.5 | MIT |  |
| `@radix-ui/react-use-is-hydrated` | 0.1.3 | MIT |  |
| `@radix-ui/react-use-layout-effect` | 1.1.4 | MIT |  |
| `@radix-ui/react-use-previous` | 1.1.4 | MIT |  |
| `@radix-ui/react-use-rect` | 1.1.4 | MIT |  |
| `@radix-ui/react-use-size` | 1.1.4 | MIT |  |
| `@radix-ui/react-visually-hidden` | 1.2.11 | MIT |  |
| `@radix-ui/rect` | 1.1.3 | MIT |  |
| `@reduxjs/toolkit` | 2.12.0 | MIT |  |
| `@standard-schema/spec` | 1.1.0 | MIT |  |
| `@standard-schema/utils` | 0.3.0 | MIT |  |
| `@tanstack/query-core` | 5.104.0 | MIT |  |
| `@tanstack/react-query` | 5.104.0 | MIT |  |
| `@tanstack/react-virtual` | 3.14.13 | MIT |  |
| `@tanstack/virtual-core` | 3.17.11 | MIT |  |
| `@types/d3-array` | 3.2.2 | MIT |  |
| `@types/d3-color` | 3.1.3 | MIT |  |
| `@types/d3-ease` | 3.0.2 | MIT |  |
| `@types/d3-interpolate` | 3.0.4 | MIT |  |
| `@types/d3-path` | 3.1.1 | MIT |  |
| `@types/d3-scale` | 4.0.9 | MIT |  |
| `@types/d3-shape` | 3.2.0 | MIT |  |
| `@types/d3-time` | 3.0.4 | MIT |  |
| `@types/d3-timer` | 3.0.2 | MIT |  |
| `@types/debug` | 4.1.13 | MIT |  |
| `@types/estree` | 1.0.9 | MIT |  |
| `@types/estree-jsx` | 1.0.5 | MIT |  |
| `@types/hast` | 3.0.5 | MIT |  |
| `@types/mdast` | 4.0.4 | MIT |  |
| `@types/ms` | 2.1.0 | MIT |  |
| `@types/prop-types` | 15.7.15 | MIT |  |
| `@types/react` | 18.3.31 | MIT |  |
| `@types/react-dom` | 18.3.7 | MIT |  |
| `@types/unist` | 3.0.3 | MIT |  |
| `@types/unist` | 2.0.11 | MIT |  |
| `@types/use-sync-external-store` | 0.0.6 | MIT |  |
| `@typescript/typescript6` | 6.0.2 | Apache-2.0 |  |
| `@ungap/structured-clone` | 1.4.0 | ISC |  |
| `agent-base` | 6.0.2 | MIT |  |
| `any-promise` | 1.3.0 | MIT |  |
| `anymatch` | 3.1.3 | ISC |  |
| `arg` | 5.0.2 | MIT |  |
| `aria-hidden` | 1.2.6 | MIT |  |
| `asynckit` | 0.4.0 | MIT |  |
| `axios` | 1.20.0 | MIT |  |
| `bail` | 2.0.2 | MIT |  |
| `binary-extensions` | 2.3.0 | MIT |  |
| `braces` | 3.0.3 | MIT |  |
| `browser-image-compression` | 2.0.2 | MIT |  |
| `call-bind-apply-helpers` | 1.0.2 | MIT |  |
| `camelcase-css` | 2.0.1 | MIT |  |
| `ccount` | 2.0.1 | MIT |  |
| `character-entities` | 2.0.2 | MIT |  |
| `character-entities-html4` | 2.1.0 | MIT |  |
| `character-entities-legacy` | 3.0.0 | MIT |  |
| `character-reference-invalid` | 2.0.1 | MIT |  |
| `chokidar` | 3.6.0 | MIT |  |
| `class-variance-authority` | 0.7.1 | Apache-2.0 |  |
| `clsx` | 2.1.1 | MIT |  |
| `cmdk` | 1.1.1 | MIT |  |
| `combined-stream` | 1.0.8 | MIT |  |
| `comma-separated-tokens` | 2.0.3 | MIT |  |
| `commander` | 4.1.1 | MIT |  |
| `cookie` | 1.1.1 | MIT |  |
| `cssesc` | 3.0.0 | MIT |  |
| `csstype` | 3.2.3 | MIT |  |
| `d3-array` | 3.2.4 | ISC |  |
| `d3-color` | 3.1.0 | ISC |  |
| `d3-ease` | 3.0.1 | BSD-3-Clause |  |
| `d3-format` | 3.1.2 | ISC |  |
| `d3-interpolate` | 3.0.1 | ISC |  |
| `d3-path` | 3.1.0 | ISC |  |
| `d3-scale` | 4.0.2 | ISC |  |
| `d3-shape` | 3.2.0 | ISC |  |
| `d3-time` | 3.1.0 | ISC |  |
| `d3-time-format` | 4.1.0 | ISC |  |
| `d3-timer` | 3.0.1 | ISC |  |
| `date-fns` | 3.6.0 | MIT |  |
| `debug` | 4.4.3 | MIT |  |
| `decimal.js-light` | 2.5.1 | MIT |  |
| `decode-named-character-reference` | 1.3.0 | MIT |  |
| `delayed-stream` | 1.0.0 | MIT |  |
| `dequal` | 2.0.3 | MIT |  |
| `detect-node-es` | 1.1.0 | MIT |  |
| `devlop` | 1.1.0 | MIT |  |
| `didyoumean` | 1.2.2 | Apache-2.0 |  |
| `dlv` | 1.1.3 | MIT |  |
| `dunder-proto` | 1.0.1 | MIT |  |
| `es-define-property` | 1.0.1 | MIT |  |
| `es-errors` | 1.3.0 | MIT |  |
| `es-object-atoms` | 1.1.2 | MIT |  |
| `es-set-tostringtag` | 2.1.0 | MIT |  |
| `es-toolkit` | 1.52.0 | MIT |  |
| `estree-util-is-identifier-name` | 3.0.0 | MIT |  |
| `eventemitter3` | 5.0.4 | MIT |  |
| `extend` | 3.0.2 | MIT |  |
| `fast-glob` | 3.3.3 | MIT |  |
| `fastq` | 1.20.3 | ISC |  |
| `fdir` | 6.5.0 | MIT |  |
| `fill-range` | 7.1.1 | MIT |  |
| `follow-redirects` | 1.16.2 | MIT |  |
| `form-data` | 4.0.6 | MIT |  |
| `function-bind` | 1.1.2 | MIT |  |
| `get-intrinsic` | 1.3.0 | MIT |  |
| `get-nonce` | 1.0.1 | MIT |  |
| `get-proto` | 1.0.1 | MIT |  |
| `glob-parent` | 6.0.2 | ISC |  |
| `glob-parent` | 5.1.2 | ISC |  |
| `gopd` | 1.2.0 | MIT |  |
| `has-symbols` | 1.1.0 | MIT |  |
| `has-tostringtag` | 1.0.2 | MIT |  |
| `hasown` | 2.0.4 | MIT |  |
| `hast-util-sanitize` | 5.0.2 | MIT |  |
| `hast-util-to-jsx-runtime` | 2.3.6 | MIT |  |
| `hast-util-whitespace` | 3.0.0 | MIT |  |
| `html-parse-stringify` | 4.0.1 | MIT |  |
| `html-url-attributes` | 3.0.1 | MIT |  |
| `html5-qrcode` | 2.3.8 | Apache-2.0 |  |
| `https-proxy-agent` | 5.0.1 | MIT |  |
| `i18next` | 26.4.2 | MIT |  |
| `i18next-browser-languagedetector` | 8.2.1 | MIT |  |
| `immer` | 11.1.18 | MIT |  |
| `inline-style-parser` | 0.2.7 | MIT |  |
| `internmap` | 2.0.3 | ISC |  |
| `is-alphabetical` | 2.0.1 | MIT |  |
| `is-alphanumerical` | 2.0.1 | MIT |  |
| `is-binary-path` | 2.1.0 | MIT |  |
| `is-core-module` | 2.17.0 | MIT |  |
| `is-decimal` | 2.0.1 | MIT |  |
| `is-extglob` | 2.1.1 | MIT |  |
| `is-glob` | 4.0.3 | MIT |  |
| `is-hexadecimal` | 2.0.1 | MIT |  |
| `is-number` | 7.0.0 | MIT |  |
| `is-plain-obj` | 4.1.0 | MIT |  |
| `jiti` | 1.21.7 | MIT |  |
| `jiti` | 2.7.0 | MIT |  |
| `js-tokens` | 4.0.0 | MIT |  |
| `lilconfig` | 3.1.3 | MIT |  |
| `lines-and-columns` | 1.2.4 | MIT |  |
| `longest-streak` | 3.1.0 | MIT |  |
| `loose-envify` | 1.4.0 | MIT |  |
| `lucide-react` | 1.48.0 | ISC |  |
| `math-intrinsics` | 1.1.0 | MIT |  |
| `mdast-util-from-markdown` | 2.0.3 | MIT |  |
| `mdast-util-mdx-expression` | 2.0.1 | MIT |  |
| `mdast-util-mdx-jsx` | 3.2.0 | MIT |  |
| `mdast-util-mdxjs-esm` | 2.0.1 | MIT |  |
| `mdast-util-phrasing` | 4.1.0 | MIT |  |
| `mdast-util-to-hast` | 13.2.1 | MIT |  |
| `mdast-util-to-markdown` | 2.1.2 | MIT |  |
| `mdast-util-to-string` | 4.0.0 | MIT |  |
| `merge2` | 1.4.1 | MIT |  |
| `micromark` | 4.0.3 | MIT |  |
| `micromark-core-commonmark` | 2.0.4 | MIT |  |
| `micromark-factory-destination` | 2.0.1 | MIT |  |
| `micromark-factory-label` | 2.0.1 | MIT |  |
| `micromark-factory-space` | 2.1.0 | MIT |  |
| `micromark-factory-title` | 2.0.1 | MIT |  |
| `micromark-factory-whitespace` | 2.0.1 | MIT |  |
| `micromark-util-character` | 2.1.1 | MIT |  |
| `micromark-util-chunked` | 2.0.1 | MIT |  |
| `micromark-util-classify-character` | 2.0.1 | MIT |  |
| `micromark-util-combine-extensions` | 2.0.1 | MIT |  |
| `micromark-util-decode-numeric-character-reference` | 2.0.2 | MIT |  |
| `micromark-util-decode-string` | 2.0.1 | MIT |  |
| `micromark-util-edit-map` | 1.0.0 | MIT |  |
| `micromark-util-encode` | 2.0.1 | MIT |  |
| `micromark-util-html-tag-name` | 2.0.1 | MIT |  |
| `micromark-util-normalize-identifier` | 2.0.1 | MIT |  |
| `micromark-util-resolve-all` | 2.0.1 | MIT |  |
| `micromark-util-sanitize-uri` | 2.0.1 | MIT |  |
| `micromark-util-subtokenize` | 2.1.0 | MIT |  |
| `micromark-util-symbol` | 2.0.1 | MIT |  |
| `micromark-util-types` | 2.0.3 | MIT |  |
| `micromatch` | 4.0.8 | MIT |  |
| `mime-db` | 1.52.0 | MIT |  |
| `mime-types` | 2.1.35 | MIT |  |
| `ms` | 2.1.3 | MIT |  |
| `mz` | 2.7.0 | MIT |  |
| `nanoid` | 3.3.20 | MIT |  |
| `normalize-path` | 3.0.0 | MIT |  |
| `object-assign` | 4.1.1 | MIT |  |
| `object-hash` | 3.0.0 | MIT |  |
| `parse-entities` | 4.0.2 | MIT |  |
| `path-parse` | 1.0.7 | MIT |  |
| `picocolors` | 1.1.1 | ISC |  |
| `picomatch` | 2.3.2 | MIT |  |
| `picomatch` | 4.0.7 | MIT |  |
| `pirates` | 4.0.7 | MIT |  |
| `postcss` | 8.5.32 | MIT |  |
| `postcss-import` | 15.1.0 | MIT |  |
| `postcss-js` | 4.1.0 | MIT |  |
| `postcss-load-config` | 6.0.1 | MIT |  |
| `postcss-nested` | 6.2.0 | MIT |  |
| `postcss-selector-parser` | 6.1.5 | MIT |  |
| `postcss-value-parser` | 4.2.0 | MIT |  |
| `property-information` | 7.2.0 | MIT |  |
| `proxy-from-env` | 2.1.0 | MIT |  |
| `queue-microtask` | 1.2.3 | MIT |  |
| `react` | 18.3.1 | MIT |  |
| `react-dom` | 18.3.1 | MIT |  |
| `react-i18next` | 17.0.15 | MIT |  |
| `react-is` | 19.3.0 | MIT |  |
| `react-markdown` | 10.1.0 | MIT |  |
| `react-redux` | 9.3.0 | MIT |  |
| `react-remove-scroll` | 2.7.2 | MIT |  |
| `react-remove-scroll-bar` | 2.3.8 | MIT |  |
| `react-router` | 7.18.4 | MIT |  |
| `react-router-dom` | 7.18.4 | MIT |  |
| `react-style-singleton` | 2.2.3 | MIT |  |
| `read-cache` | 1.0.2 | MIT |  |
| `readdirp` | 3.6.0 | MIT |  |
| `recharts` | 3.10.1 | MIT |  |
| `redux` | 5.0.1 | MIT |  |
| `redux-thunk` | 3.1.0 | MIT |  |
| `rehype-sanitize` | 6.0.0 | MIT |  |
| `remark-parse` | 11.0.0 | MIT |  |
| `remark-rehype` | 11.1.2 | MIT |  |
| `reselect` | 5.2.0 | MIT |  |
| `resolve` | 1.22.12 | MIT |  |
| `reusify` | 1.1.0 | MIT |  |
| `run-parallel` | 1.2.0 | MIT |  |
| `scheduler` | 0.23.2 | MIT |  |
| `set-cookie-parser` | 2.7.2 | MIT |  |
| `sonner` | 2.0.8 | MIT |  |
| `source-map-js` | 1.2.2 | BSD-3-Clause |  |
| `space-separated-tokens` | 2.0.2 | MIT |  |
| `stringify-entities` | 4.0.4 | MIT |  |
| `style-to-js` | 1.1.21 | MIT |  |
| `style-to-object` | 1.0.14 | MIT |  |
| `sucrase` | 3.35.1 | MIT |  |
| `supports-preserve-symlinks-flag` | 1.0.0 | MIT |  |
| `tailwind-merge` | 3.7.0 | MIT |  |
| `tailwindcss` | 3.4.19 | MIT |  |
| `tailwindcss-animate` | 1.0.7 | MIT |  |
| `thenify` | 3.3.1 | MIT |  |
| `thenify-all` | 1.6.0 | MIT |  |
| `tiny-invariant` | 1.3.3 | MIT |  |
| `tinyglobby` | 0.2.17 | MIT |  |
| `to-regex-range` | 5.0.1 | MIT |  |
| `trim-lines` | 3.0.1 | MIT |  |
| `trough` | 2.2.0 | MIT |  |
| `ts-interface-checker` | 0.1.13 | Apache-2.0 |  |
| `tslib` | 2.8.1 | 0BSD |  |
| `typescript` | 6.0.3 | Apache-2.0 |  |
| `unified` | 11.0.5 | MIT |  |
| `unist-util-is` | 6.0.1 | MIT |  |
| `unist-util-position` | 5.0.0 | MIT |  |
| `unist-util-stringify-position` | 4.0.0 | MIT |  |
| `unist-util-visit` | 5.1.0 | MIT |  |
| `unist-util-visit-parents` | 6.0.2 | MIT |  |
| `use-callback-ref` | 1.3.3 | MIT |  |
| `use-sidecar` | 1.1.3 | MIT |  |
| `use-sync-external-store` | 1.7.0 | MIT |  |
| `util-deprecate` | 1.0.2 | MIT |  |
| `uzip` | 0.20201231.0 | MIT |  |
| `vfile` | 6.0.3 | MIT |  |
| `vfile-message` | 4.0.3 | MIT |  |
| `victory-vendor` | 37.3.6 | MIT AND ISC |  |
| `web-vitals` | 6.2.2 | Apache-2.0 |  |
| `yaml` | 2.9.1 | ISC |  |
| `zustand` | 5.0.15 | MIT |  |
| `zwitch` | 2.0.4 | MIT |  |

## Backend and backup images — system layer

| Package | Version | Licence | Note |
|---|---|---|---|
| `libpango / libcairo / libgdk-pixbuf` | distro | LGPL-2.1 | loaded by WeasyPrint through ctypes at runtime; dynamic linking against unmodified shared libraries, which LGPL permits |
| `age` | distro | BSD-3-Clause | the age-encryption CLI in the db-backup image; every database dump passes through it before it is written |

## Container images

| Package | Version | Licence | Note |
|---|---|---|---|
| `postgres:17-alpine` | 17 | PostgreSQL | PostgreSQL Licence — permissive, BSD-style |
| `valkey/valkey:9.1.2-alpine` | 9.1.2 | BSD-3-Clause | the fork that stayed open source after Redis moved to RSALv2/SSPL |
| `caddy:2-alpine` | 2 | Apache-2.0 |  |
| `edoburu/pgbouncer:v1.25.2-p0` | 1.25.2 | ISC | PgBouncer is ISC; the image wrapper is MIT |
| `rclone/rclone` | 1.75.1 | MIT | offsite copy of the encrypted backups, opt-in `offsite` profile |
| `axllent/mailpit:v1.31.4` | 1.31.4 | MIT | the demo stack's catch-all mail server, so a demo visitor can read what would have gone out; opt-in `demo` profile, never part of a production deployment |
| `mailhog/mailhog:latest` | latest | MIT | development only — never part of a production deployment |
| `grafana/k6:latest` | latest | AGPL-3.0 | load-testing tool run on its own; not distributed with the product and nothing links against it |
| `grafana/grafana:latest` | latest | AGPL-3.0 | load-test dashboards only; same reasoning as k6 |
| `influxdb:1.13-alpine` | 1.13 | MIT | load-test metrics store only |

## Bundled frontend assets

| Package | Version | Licence | Note |
|---|---|---|---|
| `frontend/public/emoji` | bundled | MIT | Fluent Emoji by Microsoft (https://github.com/microsoft/fluentui-emoji); the licence ships as frontend/public/emoji/LICENSE — Copyright (c) Microsoft Corporation |
| `frontend/public/fonts` | bundled | OFL-1.1 | Plus Jakarta Sans (https://github.com/tokotype/PlusJakartaSans); the licence ships as frontend/public/fonts/OFL.txt — Copyright 2020 The Plus Jakarta Sans Project Authors |
| `frontend/public/logos` | bundled | CC0-1.0 / Trademark | nine of the twelve files are icons of Simple Icons (CC0-1.0): eight identical to 16.36.0, `openai` identical to 15.5.0 (dropped upstream in 16.0.0); the other three (Groq, Together AI, GLM) are plain shapes with no upstream source (`frontend/public/logos/README.md`). The marks are trademarks of their respective owners, the AI providers named by the file names (OpenAI, Google, Anthropic, Mistral AI, xAI, Groq and others), used only to name the provider in the AI connections screen |

## Data

Open Food Facts product data is **not** bundled as a database. The importer fetches it on request and the data is ODbL-1.0; a deployment that imports it takes on the share-alike obligation for the resulting database. The one excerpt in the repository is `backend/scripts/vision_matrix_corpus.json`: 14 barcodes with product names and brands (ODbL), and no photographs — those are fetched at run time and are CC-BY-SA. See `NOTICE`.
