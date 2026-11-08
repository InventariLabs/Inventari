"""Module scaffold generator.

Generates a new module by copying the reference module (example_widgets)
and replacing names. This ensures new modules start with working patterns
instead of empty skeletons.
"""

import json
import os
import re
from pathlib import Path

MODULES_DIR = Path(__file__).resolve().parent.parent / 'modules'
REFERENCE_MODULE = 'example_widgets'


def _to_class_name(module_name: str) -> str:
    """Convert module_name to PascalCase singular (e.g. 'bookmarks' -> 'Bookmark')."""
    parts = module_name.split('_')
    # Capitalize each part, singularize last part if it ends with 's'
    result = ''.join(p.capitalize() for p in parts)
    if result.endswith('s') and len(result) > 1:
        result = result[:-1]
    return result


def _to_title(module_name: str) -> str:
    """Convert module_name to Title Case (e.g. 'warranty_tracker' -> 'Warranty Tracker').

    Every word, not just the first: the store sits next to Equipment Tracking,
    Purchase Orders and Stock Takes, and `str.capitalize()` produced 'Warranty
    tracker' — every module written this way stood out from every module that
    was not.
    """
    return module_name.replace('_', ' ').title()


def create_module(module_name: str) -> None:
    """Creates a new module by copying the reference module."""
    src_dir = MODULES_DIR / REFERENCE_MODULE
    dst_dir = MODULES_DIR / module_name

    if dst_dir.exists():
        print(f"❌ Module '{module_name}' already exists.")
        return

    if not src_dir.exists():
        print(f"❌ Reference module '{REFERENCE_MODULE}' not found at {src_dir}.")
        return

    print(f"🚀 Creating module '{module_name}' from reference...")

    class_name = _to_class_name(module_name)
    title = _to_title(module_name)

    # Copy directory tree
    _copy_tree(src_dir, dst_dir, module_name, class_name, title)

    # Rename model file references
    _process_copied_files(dst_dir, module_name, class_name, title)

    _register_as_shipped(module_name)

    print(f"✅ Module '{module_name}' created at {dst_dir}")
    print(f'📁 Structure copied from {REFERENCE_MODULE}')
    print('💡 Next step: Restart backend to auto-discover the new module.')


#: One entry of the REPO_SHIPPED_MODULES literal, as the file writes them.
_SHIPPED_ENTRY = re.compile(r"^    '([a-z][a-z0-9_]*)',$")


def _register_as_shipped(module_name: str) -> None:
    """Put the new module on REPO_SHIPPED_MODULES, where an in-tree module belongs.

    The registry lets a manifest claim ``official`` only for a directory that
    list names, and the copied manifest claims it: left off the list, the
    module is refused at the next backend start. The list lives next to the
    modules being generated into, so a generation into a scratch tree edits
    that tree's copy. A block holding anything but plain entries is left to
    the author rather than rewritten.
    """
    safety_file = MODULES_DIR.parent / 'core' / 'module_safety.py'
    hint = f"add '{module_name}' to REPO_SHIPPED_MODULES in {safety_file} yourself"
    if not safety_file.exists():
        print(f'⚠️  {safety_file} not found — {hint}.')
        return
    text = safety_file.read_text(encoding='utf-8')
    block = re.search(r'^REPO_SHIPPED_MODULES = \{\n(.*?)^\}', text, re.M | re.S)
    lines = block.group(1).splitlines() if block else []
    names = [m.group(1) for m in map(_SHIPPED_ENTRY.match, lines) if m]
    if not block or len(names) != len(lines):
        print(f'⚠️  REPO_SHIPPED_MODULES is not a plain list of names — {hint}.')
        return
    if module_name in names:
        return
    # In front of the first name that sorts after it, every other line where
    # it was: re-sorting the list moved entries nobody asked to move (the
    # list is not in order), and the diff of a new module carried them.
    at = next((i for i, name in enumerate(names) if name > module_name), len(names))
    names.insert(at, module_name)
    body = ''.join(f"    '{name}',\n" for name in names)
    safety_file.write_text(
        text[: block.start(1)] + body + text[block.end(1) :], encoding='utf-8'
    )
    print(f'📋 Added to REPO_SHIPPED_MODULES in {safety_file}')


def _copy_tree(
    src: Path, dst: Path, module_name: str, class_name: str, title: str
) -> None:
    """Recursively copy directory, skipping __pycache__ and .pyc."""
    os.makedirs(dst, exist_ok=True)

    for item in src.iterdir():
        if item.name == '__pycache__':
            continue
        if item.suffix == '.pyc':
            continue

        dst_item = dst / item.name

        if item.is_dir():
            _copy_tree(item, dst_item, module_name, class_name, title)
        elif item.is_file():
            content = item.read_text(encoding='utf-8')
            # Replace all references to example_widgets with new module name
            content = _replace_names(content, module_name, class_name, title)
            dst_item.write_text(content, encoding='utf-8')


def _replace_names(content: str, module_name: str, class_name: str, title: str) -> str:
    """Replace all naming references in file content."""

    # Order matters: replace more specific patterns first
    replacements = [
        # Python identifiers
        ('example_widgets', module_name),
        ('ExampleWidgets', class_name + 's'),  # plural class
        ('ExampleWidget', class_name),
        # Display names / titles
        ('Example Widgets', title),
        ('Example widgets', title),
        # Frontend path references
        ('example-widgets', module_name.replace('_', '-')),
        # i18n namespace
        ('example_widgets:', f'{module_name}:'),
    ]

    for old, new in replacements:
        content = content.replace(old, new)

    return content


def _process_copied_files(
    dst_dir: Path, module_name: str, class_name: str, title: str
) -> None:
    """Post-processing: rename files, fix specific patterns."""

    # The Widget model class should be singular
    # Widget -> <ClassName> in model file
    model_file = dst_dir / 'models.py'
    if model_file.exists():
        content = model_file.read_text(encoding='utf-8')
        # Fix __tablename__ to use singular
        singular_table = (
            module_name.rstrip('s') if module_name.endswith('s') else module_name
        )
        content = content.replace(
            f"__tablename__ = '{module_name}'",
            f"__tablename__ = '{singular_table}'",
        )
        # Fix model class name (Widget -> Bookmark etc.)
        content = content.replace(f'class {class_name}s(', f'class {class_name}(')
        model_file.write_text(content, encoding='utf-8')

    # Fix schemas — singular class names
    schemas_file = dst_dir / 'schemas.py'
    if schemas_file.exists():
        content = schemas_file.read_text(encoding='utf-8')
        content = content.replace(
            f'class {class_name}sCreate', f'class {class_name}Create'
        )
        content = content.replace(
            f'class {class_name}sUpdate', f'class {class_name}Update'
        )
        content = content.replace(
            f'class {class_name}sSchema', f'class {class_name}Schema'
        )
        schemas_file.write_text(content, encoding='utf-8')

    # Fix router — singular class names and endpoint functions
    router_file = dst_dir / 'router.py'
    if router_file.exists():
        content = router_file.read_text(encoding='utf-8')
        # Fix schema imports
        content = content.replace(f'{class_name}sCreate', f'{class_name}Create')
        content = content.replace(f'{class_name}sUpdate', f'{class_name}Update')
        content = content.replace(f'{class_name}sSchema', f'{class_name}Schema')
        # Fix service imports
        content = content.replace(f'list_{module_name}s', f'list_{module_name}')
        content = content.replace(f'get_{module_name}s', f'get_{module_name}')
        content = content.replace(f'create_{module_name}s', f'create_{module_name}')
        content = response_model_fix(content, class_name)
        router_file.write_text(content, encoding='utf-8')

    # Fix service — singular class names
    service_file = dst_dir / 'service.py'
    if service_file.exists():
        content = service_file.read_text(encoding='utf-8')
        content = content.replace(f'{class_name}s', class_name)
        service_file.write_text(content, encoding='utf-8')

    # Fix module.py — no changes needed (uses define_module)

    _reset_manifest_identity(dst_dir, title)
    _reset_module_catalogs(dst_dir)

    # Fix test file
    test_file = dst_dir / 'tests' / 'integration' / f'test_{module_name}_api.py'
    if not test_file.exists():
        # Rename from example_widgets test
        src_test = dst_dir / 'tests' / 'integration' / 'test_example_widgets_api.py'
        if src_test.exists():
            src_test.rename(test_file)

    # Frontend module scaffolding is handled by frontend/scripts/generate_module.js.


def _reset_manifest_identity(dst_dir: Path, title: str) -> None:
    """Strip the reference module's identity out of the copied manifest.

    Only `name` and `display_name` were substituted, so a new module inherited
    the reference's description — a sentence about widgets, shown verbatim in
    the App Store as the first thing anyone read about it — along with its
    icon, its `system` category and the template's own version number.

    `is_reference` goes too: the store never offers a reference module, and a
    scaffold that kept the flag would be registered, working and unfindable.
    """
    manifest_file = dst_dir / 'manifest.json'
    if not manifest_file.exists():
        return

    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    manifest.pop('is_reference', None)
    manifest['description'] = f'{title} module — replace this with what it does.'
    manifest['icon'] = 'box'
    manifest['category'] = 'other'
    manifest['version'] = '0.1.0'
    manifest_file.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def _reset_module_catalogs(dst_dir: Path) -> None:
    """Replace the copied translation catalogs with empty ones.

    The reference's catalogs describe widgets in five languages, and only the
    two English strings carrying the words 'Example Widgets' were substituted —
    the Polish page title stayed 'Widgety'. Nothing reads these values anyway:
    a module's user-facing text lives in its frontend catalog, and the backend
    one is for server-generated messages the scaffold has none of yet. An empty
    catalog per language is the honest starting point. Messages sit at the top
    level of the file, where get_module_error_message reads them, so the empty
    catalog is `{}` and not an `errors` wrapper that nothing reads.
    """
    i18n_dir = dst_dir / 'i18n'
    if not i18n_dir.exists():
        return
    for catalog in i18n_dir.glob('*.json'):
        catalog.write_text('{}\n', encoding='utf-8')


def response_model_fix(content: str, class_name: str) -> str:
    """Fix response_model references in router."""
    content = content.replace(
        f'response_model=list[{class_name}sSchema]',
        f'response_model=list[{class_name}Schema]',
    )
    content = content.replace(
        f'response_model={class_name}sSchema', f'response_model={class_name}Schema'
    )
    return content
