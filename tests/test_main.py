# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportInvalidCast=false

import os
import unittest
from typing import cast
from unittest.mock import patch

import libvirt  # type: ignore[reportMissingTypeStubs]
from PyQt6.QtWidgets import QApplication

from src import main

_ = os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_APP = QApplication.instance() or QApplication([])


class DummyDomain:
    def __init__(self, name: str, active: bool) -> None:
        self._name: str = name
        self._active: bool = active
        self.start_calls: int = 0
        self.destroy_calls: int = 0
        self.raise_on_create: Exception | None = None
        self.raise_on_destroy: Exception | None = None

    def name(self) -> str:
        return self._name

    def isActive(self) -> int:
        return 1 if self._active else 0

    def create(self) -> None:
        self.start_calls += 1
        if self.raise_on_create is not None:
            raise self.raise_on_create
        self._active = True

    def destroy(self) -> None:
        self.destroy_calls += 1
        if self.raise_on_destroy is not None:
            raise self.raise_on_destroy
        self._active = False


class DummyConnection:
    def __init__(self, alive: bool, domains: list[libvirt.virDomain]) -> None:
        self._alive: bool = alive
        self._domains: list[libvirt.virDomain] = domains

    def isAlive(self) -> bool:
        return self._alive

    def listAllDomains(self) -> list[libvirt.virDomain]:
        return self._domains


class EnsureGraphicalEnvironmentTests(unittest.TestCase):
    def test_passes_with_display_variable(self) -> None:
        env = {"DISPLAY": ":0"}
        main.ensure_graphical_environment(env)

    def test_passes_with_wayland_variable(self) -> None:
        env = {"WAYLAND_DISPLAY": "wayland-0"}
        main.ensure_graphical_environment(env)

    def test_fails_without_display_variables(self) -> None:
        with self.assertRaises(AssertionError) as ctx:
            main.ensure_graphical_environment({})

        message = str(ctx.exception)
        self.assertIn("No graphical display detected", message)
        self.assertIn("export DISPLAY=:0", message)


class ConnectToLibvirtTests(unittest.TestCase):
    def test_fail_fast_when_open_returns_none(self) -> None:
        with patch("src.main.libvirt.open", return_value=None):
            with self.assertRaises(AssertionError):
                _ = main.connect_to_libvirt()


class GetVmsTests(unittest.TestCase):
    def test_requires_alive_connection(self) -> None:
        conn = cast(libvirt.virConnect, DummyConnection(alive=False, domains=[]))

        with self.assertRaises(AssertionError):
            _ = main.get_vms(conn)


class BuildMenuTests(unittest.TestCase):
    def test_submenus_reflect_vm_status(self) -> None:
        running = DummyDomain("vm-running", active=True)
        stopped = DummyDomain("vm-stopped", active=False)

        menu = main.build_menu(
            [
                main.VMInfo(name="vm-running", status="running", domain=cast(libvirt.virDomain, running)),
                main.VMInfo(name="vm-stopped", status="shut off", domain=cast(libvirt.virDomain, stopped)),
            ]
        )

        actions = list(menu.actions())
        self.assertGreaterEqual(len(actions), 3)

        self.assertEqual(actions[0].text(), "vm-running (running)")
        running_menu = actions[0].menu()
        if running_menu is None:
            self.fail("Running VM submenu missing")
        self.assertIn("Stop", [action.text() for action in running_menu.actions()])

        self.assertEqual(actions[1].text(), "vm-stopped (shut off)")
        stopped_menu = actions[1].menu()
        if stopped_menu is None:
            self.fail("Stopped VM submenu missing")
        self.assertIn("Start", [action.text() for action in stopped_menu.actions()])

        quit_actions = [action for action in actions if action.text() == "Quit"]
        self.assertEqual(len(quit_actions), 1)

    def test_shows_placeholder_when_no_vms(self) -> None:
        menu = main.build_menu([])
        texts = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertIn("No VMs found", texts)


class StartVmTests(unittest.TestCase):
    def test_reports_libvirt_error(self) -> None:
        domain = DummyDomain("test", active=False)
        domain.raise_on_create = libvirt.libvirtError("boom")

        with patch("src.main.QMessageBox.critical") as mocked_message:
            main.start_vm(cast(libvirt.virDomain, domain))

        mocked_message.assert_called_once()
        self.assertEqual(domain.start_calls, 1)


class StopVmTests(unittest.TestCase):
    def test_destroy_called_when_active(self) -> None:
        domain = DummyDomain("active", active=True)

        main.stop_vm(cast(libvirt.virDomain, domain))

        self.assertEqual(domain.destroy_calls, 1)

    def test_destroy_not_called_when_inactive(self) -> None:
        domain = DummyDomain("inactive", active=False)

        main.stop_vm(cast(libvirt.virDomain, domain))

        self.assertEqual(domain.destroy_calls, 0)


if __name__ == "__main__":
    _ = unittest.main()
