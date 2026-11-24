"""The images a release publishes are exactly the ones the production file builds.

`docker-compose.prod.yml` builds three services from this tree. The release
workflow publishes an image for each, and `docker-compose.images.yml` swaps the
build for that image. If one of the three drifts — a service gains a `build:`,
the workflow forgets a context, the images file names an image the workflow
never pushes — an installation that pulls would run a stack the file in front
of it does not describe, or fail on a tag that does not exist.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(
    os.environ.get('INVENTARI_REPO_ROOT') or Path(__file__).resolve().parents[3]
)

_REGISTRY = 'ghcr.io/inventarilabs/inventari-'


def _load(name: str) -> dict:
    """A YAML file, with compose's `!reset` and `!override` tags read as the
    plain value they decorate."""
    text = (_REPO_ROOT / name).read_text(encoding='utf-8')
    return yaml.safe_load(re.sub(r'!(?:reset|override) ?', '', text))


def _built_by_production() -> dict[str, str]:
    """Service name -> build context, for every service the file builds."""
    services = _load('docker-compose.prod.yml')['services']
    return {
        name: Path(service['build']['context']).as_posix().removeprefix('./')
        for name, service in services.items()
        if 'build' in service
    }


def _published_by_workflow() -> dict[str, str]:
    """Image suffix -> build context, from the release workflow's matrix."""
    workflow = _load('.github/workflows/release-images.yml')
    matrix = workflow['jobs']['images']['strategy']['matrix']['include']
    return {entry['image']: entry['context'] for entry in matrix}


def test_the_images_file_replaces_every_build_and_only_those():
    built = set(_built_by_production())
    swapped = {
        name
        for name, service in _load('docker-compose.images.yml')['services'].items()
        if 'image' in service
    }

    assert built == swapped


def test_each_image_the_file_pulls_is_one_the_workflow_pushes():
    published = _published_by_workflow()
    services = _load('docker-compose.images.yml')['services']

    pulled = {
        re.fullmatch(rf'{re.escape(_REGISTRY)}([a-z]+):.*', s['image']).group(1)
        for s in services.values()
    }

    assert pulled == set(published)


def test_the_workflow_builds_the_context_the_service_builds_from():
    published = _published_by_workflow()
    images = {
        name: re.fullmatch(rf'{re.escape(_REGISTRY)}([a-z]+):.*', s['image']).group(1)
        for name, s in _load('docker-compose.images.yml')['services'].items()
    }

    for service, context in _built_by_production().items():
        assert published[images[service]] == context


def test_every_image_is_pinned_to_the_release_with_no_default():
    for service in _load('docker-compose.images.yml')['services'].values():
        assert ':${INVENTARI_VERSION:?' in service['image'], (
            'a missing version must stop `up`, not pull whatever `latest` is'
        )


def test_the_workflow_builds_both_architectures():
    steps = _load('.github/workflows/release-images.yml')['jobs']['images']['steps']
    build = next(s for s in steps if s.get('uses', '').startswith('docker/build-push'))

    assert build['with']['platforms'] == 'linux/amd64,linux/arm64'


def test_the_frontend_bundle_is_not_built_under_emulation():
    """The static files are the same on every architecture; building them for
    the target platform would run the whole Vite build in QEMU on arm64."""
    dockerfile = (_REPO_ROOT / 'frontend/Dockerfile').read_text(encoding='utf-8')

    assert re.search(
        r'^FROM --platform=\$BUILDPLATFORM node:\S+ AS builder', dockerfile, re.M
    )
