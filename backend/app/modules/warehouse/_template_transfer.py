"""Export and import of a document template as one file.

A template leaves the installation as a single JSON file and arrives on
another through the same door a hand-typed template uses. The file is
untrusted data: the import parses it, checks every field it references
against the context the renderer actually carries, and renders it on the
example document — nothing more. What passes is saved through the ordinary
create path, so the sandboxed engine and the render-time sanitizer stay
the only things that ever execute it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from jinja2 import nodes
from jinja2.exceptions import TemplateSyntaxError
from jinja2.sandbox import SandboxedEnvironment

from app.core.exceptions import ValidationException, catalogue_refusal
from app.core.public_api import core_api
from app.core.template_schemas import BODY_MAX_LENGTH, DocumentTemplateSchema

#: Marks the file as this project's template export. A stranger's JSON with
#: the same field names but another kind is refused, not guessed at.
EXPORT_KIND = 'inventari.document-template'
EXPORT_VERSION = 1

#: The columns the names land in — the same ceilings the table enforces.
_NAME_MAX = 255
_TYPE_MAX = 50


def _refuse(key: str, **kwargs: Any) -> ValidationException:
    return catalogue_refusal(key, **kwargs)


def build_export_file(template: DocumentTemplateSchema) -> tuple[str, bytes]:
    """One file carrying everything the import needs to recreate it.

    Returns ``(filename, bytes)``. Deliberately no instance identity — no
    ids, no timestamps, no organization — the file must land on another
    installation as if the template had been typed there.
    """
    payload = {
        'kind': EXPORT_KIND,
        'version': EXPORT_VERSION,
        'name': template.name,
        'document_type': template.document_type,
        'is_default': template.is_default,
        'body_html': template.body_html,
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2).encode('utf-8')
    return _export_filename(template.name), raw


def _export_filename(name: str) -> str:
    slug = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('._') or 'template'
    return f'{slug}.json'


def parse_export_file(raw: bytes) -> dict[str, Any]:
    """Read one exported file and refuse anything that is not one.

    Unknown extra fields are ignored, not refused — a file exported by a
    newer version still imports what this version understands, and the
    version gate above is where forward-incompatibility is decided.
    """
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _refuse('template_import_not_json') from exc
    if not isinstance(data, dict) or data.get('kind') != EXPORT_KIND:
        raise _refuse('template_import_wrong_kind')
    version = data.get('version')
    if not isinstance(version, int) or isinstance(version, bool):
        raise _refuse('template_import_invalid_field', field='version')
    if version != EXPORT_VERSION:
        raise _refuse(
            'template_import_wrong_version',
            version=version,
            supported=EXPORT_VERSION,
        )
    return {
        'name': _required_text(data, 'name', _NAME_MAX),
        # The same ceiling the create schema puts on the editor's save —
        # an import must not produce a template the editor cannot keep.
        'body_html': _required_text(data, 'body_html', BODY_MAX_LENGTH),
        'document_type': _optional_text(data, 'document_type', _TYPE_MAX, 'DEFAULT'),
        'is_default': _optional_bool(data, 'is_default', False),
    }


def _required_text(data: dict[str, Any], key: str, max_len: int | None) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _refuse('template_import_invalid_field', field=key)
    if max_len is not None and len(value) > max_len:
        raise _refuse('template_import_invalid_field', field=key)
    return value


def _optional_text(data: dict[str, Any], key: str, max_len: int, default: str) -> str:
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip() or len(value) > max_len:
        raise _refuse('template_import_invalid_field', field=key)
    return value


def _optional_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise _refuse('template_import_invalid_field', field=key)
    return value


def validate_body(body_html: str) -> None:
    """Parse, check every referenced field, render — the import's whole
    evaluation of the file.

    The existence oracle is the real render context (internal keys
    included): the catalog hides ``doc_variant`` or ``discrepancy_map``
    from authors, yet the shipped layouts — and so every copy of them a
    user exports — are written in terms of them. A reference that exists
    renders; one that does not would print nothing, and is refused here,
    by name, while the file is still at hand.
    """
    env = SandboxedEnvironment()
    try:
        ast = env.parse(body_html)
    except TemplateSyntaxError as exc:
        raise _refuse('template_import_not_renderable', detail=str(exc)) from exc

    context = _example_context()
    stored, loaded = _names(ast)
    unknown = sorted(loaded - stored - context.keys() - _TEMPLATE_PROVIDED)
    if unknown:
        raise _refuse(
            'template_import_unknown_placeholders',
            placeholders=', '.join(unknown),
        )

    unknown_attrs = _unknown_attribute_paths(ast, context)
    if unknown_attrs:
        raise _refuse(
            'template_import_unknown_placeholders',
            placeholders=', '.join(unknown_attrs),
        )

    try:
        # The same render, on the same example document, the preview and
        # the placeholders catalog use — includes resolved from the
        # module's own directory and no further.
        core_api.pdf.render_html(body_html, context, templates_dir=_templates_dir())
    except Exception as exc:  # an untrusted file's every failure is a refusal
        raise _refuse('template_import_not_renderable', detail=str(exc)) from exc


#: Names a template does not take from the render context: the loop
#: variable Jinja puts inside every ``{% for %}``, and the environment's
#: own globals (``range``, ``namespace``, …).
_TEMPLATE_PROVIDED = frozenset({'loop', *SandboxedEnvironment().globals})


def _names(ast: nodes.Template) -> tuple[set[str], set[str]]:
    """Every name the template assigns, and every one it reads.

    A plain walk, not ``meta.find_undeclared_variables``: that one treats a
    name assigned inside a ``{% for %}`` body (``{% set total = … %}``) as
    undeclared even when read in the same body — and the shipped layouts
    total their columns exactly that way, so the standard oracle would
    refuse every copy of them.

    A macro is the same kind of name: ``{% macro cell(…) %}`` assigns it,
    the layout calls it, and neither the call nor the definition reads the
    render context for it. The Macro node carries the name as a string —
    a Name walk alone sees the call's load and never a store, so a layout
    with a macro of its own (the pl_pz totals row) would be refused as
    referencing a field that does not exist.
    """
    stored: set[str] = set()
    loaded: set[str] = set()
    for node in ast.find_all(nodes.Name):
        # 'param' is a macro argument — assigned by the call, not read
        # from the context.
        if node.ctx in ('store', 'param'):
            stored.add(node.name)
        else:
            loaded.add(node.name)
    for macro in ast.find_all(nodes.Macro):
        stored.add(macro.name)
    return stored, loaded


#: Marks a value the example context cannot produce for a chain the AST
#: carries — the chain is left to the render, not refused on a guess.
_UNRESOLVED = object()


def _unknown_attribute_paths(ast: nodes.Template, context: dict[str, Any]) -> list[str]:
    """Dotted references the example context cannot resolve.

    The root check above answers ``{{ madeup }}``; this answers
    ``{{ partner.nonexistent_field }}`` — which renders as an empty
    paragraph, silence where the author asked a question. Every attribute
    chain in the AST is followed on the example context, the same oracle
    the root check reads, so a typo is named the way the placeholders
    catalog writes it: as a dotted path.

    Loop variables are bound from their iterated value —
    ``{% for line in document.lines %}`` makes ``line`` an example line —
    so a bogus column on a line is refused exactly like one on the
    document. A chain the example cannot carry — an optional the layout
    guards with ``{% if … %}`` and leaves ``None`` here, or a name the
    template assigns itself (``{% set %}``, a macro parameter, Jinja's
    own ``loop``) — is left to the render: refusing it would turn away a
    layout that works on real data.
    """
    values = _bind_loops(ast, context)
    unknown: list[str] = []
    for node in ast.find_all(nodes.Getattr):
        chain = _chain(node)
        if chain is None:
            continue
        root, attrs = chain
        if root not in values:
            continue
        dotted = root
        value: Any = values[root]
        for attr in attrs:
            if value is None:
                break  # a guarded optional — the render decides
            if not _has_attribute(value, attr):
                unknown.append(f'{dotted}.{attr}')
                break
            value = _read_attribute(value, attr)
            dotted = f'{dotted}.{attr}'
    return unknown


def _bind_loops(ast: nodes.Template, context: dict[str, Any]) -> dict[str, Any]:
    """The example context plus every loop variable bound to an example
    element — the walk's answer to "what is ``line`` here"."""
    values = dict(context)
    for node in ast.find_all(nodes.For):
        source = _static_value(node.iter, values)
        if source is _UNRESOLVED:
            continue
        first = _first_element(source)
        if first is _UNRESOLVED:
            continue
        names = _target_names(node.target)
        if len(names) == 1:
            values[names[0]] = first
        elif isinstance(first, (list, tuple)) and len(first) == len(names):
            # ``{% for k, v in …items() %}`` — the example element unpacks.
            values.update(zip(names, first, strict=True))
        else:
            # Present but unverifiable: the chains are left to the render.
            values.update(dict.fromkeys(names))
    return values


def _static_value(node: nodes.Node, values: dict[str, Any]) -> Any:
    """The value a Jinja expression stands for when it is a plain dotted
    chain from a name the example context resolves; ``_UNRESOLVED``
    otherwise (a call, a filter, a name no example value answers)."""
    if isinstance(node, nodes.Name):
        return values.get(node.name, _UNRESOLVED)
    if isinstance(node, nodes.Getattr):
        chain = _chain(node)
        if chain is None:
            return _UNRESOLVED
        root, attrs = chain
        if root not in values:
            return _UNRESOLVED
        value: Any = values[root]
        for attr in attrs:
            if value is None or not _has_attribute(value, attr):
                return _UNRESOLVED
            value = _read_attribute(value, attr)
        return value
    return _UNRESOLVED


def _chain(node: nodes.Getattr) -> tuple[str, list[str]] | None:
    """The dotted path a Getattr node spells: ``(root, [attr, …])`` from
    the outermost attribute down to the name it hangs on. Anything but a
    plain load of a name — a call, a subscript — is not a chain."""
    attrs = [node.attr]
    current: nodes.Node = node.node
    while isinstance(current, nodes.Getattr):
        attrs.append(current.attr)
        current = current.node
    if not isinstance(current, nodes.Name) or current.ctx != 'load':
        return None
    attrs.reverse()
    return current.name, attrs


def _target_names(target: nodes.Node) -> list[str]:
    """The names a ``{% for %}`` target binds — one, or the tuple form."""
    if isinstance(target, nodes.Name):
        return [target.name]
    if isinstance(target, (nodes.Tuple, nodes.List)):
        names: list[str] = []
        for item in target.items:
            names.extend(_target_names(item))
        return names
    return []


def _first_element(source: Any) -> Any:
    """The element a loop's first pass would see. Jinja iterates a dict's
    keys; a sequence yields its first item; anything else, or nothing to
    iterate, is no example at all."""
    if isinstance(source, (list, tuple, str)):
        return source[0] if source else _UNRESOLVED
    if isinstance(source, dict):
        return next(iter(source), _UNRESOLVED)
    return _UNRESOLVED


def _has_attribute(value: Any, attr: str) -> bool:
    """Whether Jinja's lookup finds anything here — attribute first, then
    subscript, the same two doors ``environment.getattr`` tries."""
    try:
        getattr(value, attr)
        return True
    except AttributeError:
        pass
    except Exception:  # noqa: BLE001 — a property that raises is not a readable field
        # A property that raises on the example document is not a field a
        # template can read; the render will say so in its own words.
        return False
    try:
        value[attr]
        return True
    except Exception:  # noqa: BLE001 — any lookup failure means the field is not there
        return False


def _read_attribute(value: Any, attr: str) -> Any:
    try:
        return getattr(value, attr)
    except AttributeError:
        return value[attr]


def _templates_dir() -> Any:
    from pathlib import Path

    return Path(__file__).resolve().parent / 'templates'


def _example_context() -> dict[str, Any]:
    # Imported here, not at the top: the router imports this module for its
    # endpoints, and the example document lives there — the same context
    # the preview and the placeholders catalog are built from.
    from .documents_templates_router import _example_context as build_example

    return build_example()
