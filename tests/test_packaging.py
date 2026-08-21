"""
Packaging Tests
================

Consistency checks across the Arch packaging files.

The package names live in three places - the ``pkgname`` array, the
``package_*()`` functions and the installer script - and the GNOME
extension's uuid lives in two: ``metadata.json`` and the PKGBUILD that
names the directory it installs into.  None of those duplications fail
loudly when they drift: a renamed package makes the installer stop
finding it, and a diverged uuid makes GNOME Shell quietly never load the
extension.  These tests are what turns either into a failing build.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PKGBUILD = (_REPO_ROOT / 'packaging' / 'arch' / 'PKGBUILD').read_text(encoding='utf-8')
_INSTALLER = (_REPO_ROOT / 'packaging' / 'arch' / 'install.sh').read_text(encoding='utf-8')


def _declared_package_names() -> list[str]:
    """Return the names in the PKGBUILD's ``pkgname`` array."""
    match = re.search(r'^pkgname=\((.*?)\)$', _PKGBUILD, re.MULTILINE | re.DOTALL)
    assert match is not None, 'pkgname array not found in PKGBUILD'
    return re.findall(r"'([^']+)'", match.group(1))


def _packaging_functions() -> list[str]:
    """Return the package names the ``package_*()`` functions build."""
    return re.findall(r'^package_(\S+)\(\)', _PKGBUILD, re.MULTILINE)


def _installer_package_names() -> list[str]:
    """Return the package names the installer script hands to pacman."""
    return re.findall(r"^readonly \w+_PACKAGE='([^']+)'$", _INSTALLER, re.MULTILINE)


class TestPackageNames(unittest.TestCase):

    def test_every_declared_package_has_a_build_function(self):
        self.assertEqual(sorted(_declared_package_names()), sorted(_packaging_functions()))

    def test_the_installer_only_references_real_packages(self):
        declared = set(_declared_package_names())
        referenced = set(_installer_package_names())

        self.assertTrue(referenced, 'no package constants found - did install.sh get restructured?')
        self.assertEqual(referenced - declared, set(), 'install.sh references packages the PKGBUILD does not build')

    def test_the_installer_covers_every_package(self):
        # A frontend added to the PKGBUILD but not to the installer would be
        # built on every run and never installed by anyone.
        self.assertEqual(set(_declared_package_names()) - set(_installer_package_names()), set())


class TestGnomeExtensionUuid(unittest.TestCase):

    def setUp(self):
        metadata_path = _REPO_ROOT / 'frontends' / 'gnome' / 'metadata.json'
        self.uuid = json.loads(metadata_path.read_text(encoding='utf-8'))['uuid']

    def test_pkgbuild_installs_into_the_uuid_directory(self):
        # GNOME Shell resolves an extension by uuid: the installed directory
        # has to be named after it or the shell never loads the extension.
        match = re.search(r"^\s*local uuid='([^']+)'$", _PKGBUILD, re.MULTILINE)
        self.assertIsNotNone(match, 'the GNOME package function no longer declares a uuid')
        self.assertEqual(match.group(1), self.uuid)

    def test_the_installer_prints_the_same_uuid(self):
        # The post-install hint tells the user which extension to enable;
        # a stale uuid there sends them to a command that does nothing.
        self.assertIn(self.uuid, _INSTALLER)


if __name__ == '__main__':
    unittest.main()
