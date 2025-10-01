import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src import main


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
                main.connect_to_libvirt()


class GetVmsTests(unittest.TestCase):
    def test_requires_alive_connection(self) -> None:
        conn = MagicMock()
        conn.isAlive.return_value = False

        with self.assertRaises(AssertionError):
            main.get_vms(conn)


class QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])


class BuildMenuTests(QtTestCase):
    def test_submenus_reflect_vm_status(self) -> None:
        running_domain = MagicMock()
        stopped_domain = MagicMock()

        running_vm = main.VMInfo(name="vm-running", status="running", domain=running_domain)
        stopped_vm = main.VMInfo(name="vm-stopped", status="shut off", domain=stopped_domain)

        menu = main.build_menu([running_vm, stopped_vm])

        actions = menu.actions()
        self.assertEqual(actions[0].text(), "vm-running (running)")
        running_menu = actions[0].menu()
        self.assertIsNotNone(running_menu)
        self.assertIn("Stop", [action.text() for action in running_menu.actions()])

        self.assertEqual(actions[1].text(), "vm-stopped (shut off)")
        stopped_menu = actions[1].menu()
        self.assertIsNotNone(stopped_menu)
        self.assertIn("Start", [action.text() for action in stopped_menu.actions()])

        # Last non-separator action should be Quit
        quit_action = [action for action in actions if action.text() == "Quit"]
        self.assertEqual(len(quit_action), 1)

    def test_shows_placeholder_when_no_vms(self) -> None:
        menu = main.build_menu([])
        texts = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertIn("No VMs found", texts)


class StartVmTests(unittest.TestCase):
    def test_reports_libvirt_error(self) -> None:
        domain = MagicMock()
        domain.create.side_effect = main.libvirt.libvirtError("boom")

        with patch("src.main.QMessageBox.critical") as mocked_message:
            main.start_vm(domain)

        mocked_message.assert_called_once()


class StopVmTests(unittest.TestCase):
    def test_destroy_called_when_active(self) -> None:
        domain = MagicMock()
        domain.isActive.return_value = True

        main.stop_vm(domain)

        domain.destroy.assert_called_once_with()

    def test_destroy_not_called_when_inactive(self) -> None:
        domain = MagicMock()
        domain.isActive.return_value = False

        main.stop_vm(domain)

        domain.destroy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
