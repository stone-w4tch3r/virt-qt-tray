# pyright: reportMissingTypeStubs=false

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import libvirt  # type: ignore[reportMissingTypeStubs]
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication, QStyle

from src import main

_ = os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_APP = cast(QApplication, QApplication.instance() or QApplication([]))


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


class GetVmsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=2)

    async def asyncTearDown(self) -> None:
        self.executor.shutdown(wait=False)

    async def test_requires_alive_connection(self) -> None:
        conn = cast(libvirt.virConnect, DummyConnection(alive=False, domains=[]))

        with self.assertRaises(AssertionError):
            _ = await main.get_vms(conn, self.executor)

    async def test_retrieves_vm_list(self) -> None:
        running = DummyDomain("vm-running", active=True)
        stopped = DummyDomain("vm-stopped", active=False)
        conn = cast(
            libvirt.virConnect,
            DummyConnection(
                alive=True,
                domains=[
                    cast(libvirt.virDomain, running),
                    cast(libvirt.virDomain, stopped),
                ],
            ),
        )

        vms = await main.get_vms(conn, self.executor)

        self.assertEqual(len(vms), 2)
        self.assertEqual(vms[0]["name"], "vm-running")
        self.assertEqual(vms[0]["status"], "running")
        self.assertEqual(vms[1]["name"], "vm-stopped")
        self.assertEqual(vms[1]["status"], "shut off")


class BuildMenuTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=2)

    def tearDown(self) -> None:
        self.executor.shutdown(wait=False)

    def test_submenus_reflect_vm_status(self) -> None:
        running = DummyDomain("vm-running", active=True)
        stopped = DummyDomain("vm-stopped", active=False)

        menu = main.build_menu(
            [
                main.VMInfo(
                    name="vm-running",
                    status="running",
                    domain=cast(libvirt.virDomain, running),
                ),
                main.VMInfo(
                    name="vm-stopped",
                    status="shut off",
                    domain=cast(libvirt.virDomain, stopped),
                ),
            ],
            self.executor,
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
        menu = main.build_menu([], self.executor)
        texts = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertIn("No VMs found", texts)


class StartVmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=2)

    async def asyncTearDown(self) -> None:
        self.executor.shutdown(wait=False)

    async def test_calls_domain_create(self) -> None:
        domain = DummyDomain("test", active=False)

        await main.start_vm(cast(libvirt.virDomain, domain), self.executor)

        self.assertEqual(domain.start_calls, 1)
        self.assertTrue(domain._active)

    async def test_reports_libvirt_error(self) -> None:
        domain = DummyDomain("test", active=False)
        domain.raise_on_create = libvirt.libvirtError("boom")

        with patch("src.main.QMessageBox.critical") as mocked_message:
            await main.start_vm(cast(libvirt.virDomain, domain), self.executor)

        mocked_message.assert_called_once()
        self.assertEqual(domain.start_calls, 1)


class StopVmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=2)

    async def asyncTearDown(self) -> None:
        self.executor.shutdown(wait=False)

    async def test_destroy_called_when_active(self) -> None:
        domain = DummyDomain("active", active=True)

        await main.stop_vm(cast(libvirt.virDomain, domain), self.executor)

        self.assertEqual(domain.destroy_calls, 1)
        self.assertFalse(domain._active)

    async def test_destroy_not_called_when_inactive(self) -> None:
        domain = DummyDomain("inactive", active=False)

        await main.stop_vm(cast(libvirt.virDomain, domain), self.executor)

        self.assertEqual(domain.destroy_calls, 0)


class ResolveTrayIconTests(unittest.TestCase):
    def test_env_override_used_when_available(self) -> None:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.blue)
        themed_icon = QIcon(pixmap)

        with patch.dict(os.environ, {"VM_TRAY_ICON_NAME": "custom-icon"}, clear=False):
            with patch("src.main.QIcon.fromTheme", return_value=themed_icon) as mock_from_theme:
                resolved = main.resolve_tray_icon(_APP)

        mock_from_theme.assert_called_once_with("custom-icon")
        self.assertFalse(resolved.isNull())

    def test_fallback_to_style_icon_when_theme_missing(self) -> None:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.green)
        style_icon = QIcon(pixmap)

        with patch.object(main, "BASE_ICON_FILE", Path("/nonexistent")):
            with patch("src.main.QIcon.fromTheme", return_value=QIcon()) as mock_from_theme:
                style = MagicMock()
                style.standardIcon.return_value = style_icon
                with patch.object(_APP, "style", return_value=style):
                    resolved = main.resolve_tray_icon(_APP)

        self.assertTrue(mock_from_theme.called)
        style.standardIcon.assert_called_once_with(QStyle.StandardPixmap.SP_ComputerIcon)
        self.assertFalse(resolved.isNull())

    def test_final_fallback_creates_pixmap(self) -> None:
        with patch.object(main, "BASE_ICON_FILE", Path("/nonexistent")):
            with patch("src.main.QIcon.fromTheme", return_value=QIcon()):
                style = MagicMock()
                style.standardIcon.return_value = QIcon()
                with patch.object(_APP, "style", return_value=style):
                    resolved = main.resolve_tray_icon(_APP)

        self.assertFalse(resolved.isNull())

    def test_path_override_icon(self) -> None:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.yellow)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            pixmap.save(tmp.name, "PNG")
            temp_path = tmp.name

        try:
            with patch.dict(os.environ, {"VM_TRAY_ICON_PATH": temp_path}, clear=False):
                icon = main.resolve_tray_icon(_APP)
        finally:
            os.unlink(temp_path)

        self.assertFalse(icon.isNull())


class IconWithRunningIndicatorTests(unittest.TestCase):
    def test_indicator_draws_colored_dot(self) -> None:
        base_pixmap = QPixmap(32, 32)
        base_pixmap.fill(Qt.GlobalColor.lightGray)
        base_icon = QIcon(base_pixmap)

        palette = _APP.palette()
        highlight_color = palette.color(QPalette.ColorRole.Highlight)
        palette.setColor(QPalette.ColorRole.Highlight, Qt.GlobalColor.red)

        with patch.object(_APP, "palette", return_value=palette):
            icon = main.icon_with_running_indicator(base_icon, _APP)

        pixmap = icon.pixmap(32, 32)
        image = pixmap.toImage()
        top_right = image.pixelColor(pixmap.width() - 4, 4)
        bottom_left = image.pixelColor(4, pixmap.height() - 4)
        self.assertNotEqual(top_right, bottom_left)
        # restore palette highlight
        palette.setColor(QPalette.ColorRole.Highlight, highlight_color)


if __name__ == "__main__":
    _ = unittest.main()
