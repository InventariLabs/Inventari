# AI provider brand marks

The SVG files in this directory are the brand/logo marks of the AI providers
selectable in the **AI connections** settings screen. They are rendered by
`ProviderLogo` to identify the provider, and nothing else.

## Provenance

Checked on 2026-10-27 by comparing each file's path data with the icons of
[Simple Icons](https://github.com/simple-icons/simple-icons) 16.36.0 (and,
for `openai`, 15.5.0), which is licensed CC0-1.0:

| File | Source |
|---|---|
| `anthropic`, `deepseek`, `google`, `minimax`, `openrouter`, `xiaomi` | identical to the Simple Icons 16.36.0 icon of the same name |
| `openai` | identical to the Simple Icons 15.5.0 icon `openai`; Simple Icons dropped that icon in 16.0.0, so 16.36.0 no longer has it |
| `mistral` | identical to Simple Icons `mistralai` |
| `xai` | identical to Simple Icons `x` (the mark xAI uses) |
| `groq`, `together`, `glm` | match no Simple Icons icon. Plain geometric shapes (a hexagonal box, two circles, a disc with a Z) that stand in for the provider; no upstream source is known and they are not the owners' official artwork |

All twelve are 24×24 SVGs with a `role="img"` and a `<title>`. If a mark is
replaced or updated from another source, record that here.

## Trademark

Each mark is the property of its respective owner (for example, "OpenAI",
"Google", "Anthropic", "Mistral AI", "xAI", "Groq" and the others named by the
file names). Their use here is for identification of the corresponding service
in the connection UI only and does not imply endorsement, sponsorship, or
affiliation.
