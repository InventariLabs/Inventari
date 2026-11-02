from typing import Literal

from pydantic import BaseModel, Field

from app.core.module_manifest_schema import ModuleCategory


class ModuleInfo(BaseModel):
    name: str
    display_name: str
    description: str
    icon: str
    module_type: Literal['core', 'official', 'cloud', 'community']
    #: Declared resources the module touches. Not a security boundary:
    #: information for the operator deciding to switch it on.
    #: No default: on the one screen that shows this, "not declared" and
    #: "touches nothing" must not be the same answer.
    capabilities: list[str]
    # The store groups by this. It arrives from the manifest so that a module
    # without a launcher tile still lands somewhere findable.
    category: ModuleCategory = 'other'
    requires: list[str] = []
    #: Companions the module integrates with but does not need. The store
    #: warns when one is switched off; enabling is never blocked by it.
    optional_requires: list[str] = []
    version: str = '0.1.0'
    #: None means nobody signed the module — an anonymous community module is
    #: exactly that, never "Core Team" (see ModuleManifest.author).
    #:
    #: Both fields come off the package's own ``module.yaml``, so on their
    #: own they are a claim, not a fact. What decides which one the reader
    #: is looking at is ``signature_status`` below: the digest covers
    #: ``module.yaml``, so a verified signature means the holder of that key
    #: published exactly this author and this licence.
    author: str | None = None
    license: str | None = None
    #: What the install verified about the package, or None for a module
    #: that is part of the tree — its code is in the repository, and a
    #: signature line about it would be theatre.
    signature_status: Literal['verified', 'unsigned'] | None = None
    #: The key id a verified signature belongs to. Never set for an
    #: unsigned install: there is nobody to name.
    signed_by: str | None = None
    homepage: str | None = None
    requires_api_key: bool = False
    is_trusted: bool = False
    is_always_on: bool = False
    safety_warnings: list[str] = []
    is_configured: bool = True
    is_premium: bool = False
    degraded: bool = False
    #: Whether this installation has screens for the module.
    #: 'present'    — it does (everything in the tree, and every complete install)
    #: 'headless'   — the module ships none and never claimed to
    #: 'incomplete' — it ships some, and this installation did not get them
    #: The store needs the distinction: a module with no interface is a fact
    #: worth showing before someone switches it on, and 'why' differs.
    frontend_state: Literal['present', 'headless', 'incomplete'] = 'present'


class ModuleToggle(BaseModel):
    module_name: str
    enabled: bool


class FocusModeRequest(BaseModel):
    module_name: str = Field(min_length=1, max_length=50)


class FocusModeDiff(BaseModel):
    """The planned enabled-set delta for entering single-module focus mode.

    Mirrors the profile-switch diff: ``disable``/``cascade_disable`` are what
    switches off (with the cascade naming its reason in ``warnings``), and
    ``final_enabled_modules`` is the enabled set the mode settles on.
    """

    focus_module: str
    enable: list[str]
    disable: list[str]
    cascade_disable: list[str]
    disable_all: list[str]
    unchanged: list[str]
    manual_kept: list[str]
    final_enabled_modules: list[str]
    warnings: list[str] = Field(default_factory=list)


class FocusModeResponse(BaseModel):
    applied: bool
    focus_module: str | None = None
    enabled_modules: list[str] = Field(default_factory=list)
    diff: FocusModeDiff | None = None
