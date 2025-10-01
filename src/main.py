import os
import sys
from collections.abc import Mapping
from typing import TypedDict, List
import libvirt  # type: ignore[attr-defined]  # Suppress untyped import warning
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon


# Define typed structure for VM information
class VMInfo(TypedDict):
    name: str
    status: str
    domain: libvirt.virDomain


def ensure_graphical_environment(env: Mapping[str, str] | None = None) -> None:
    """Fail fast when no GUI session is available (e.g. plain SSH)."""
    vars_to_check = env if env is not None else os.environ
    has_x11 = bool(vars_to_check.get("DISPLAY"))
    has_wayland = bool(vars_to_check.get("WAYLAND_DISPLAY"))
    assert has_x11 or has_wayland, (
        "No graphical display detected. Run inside an X11/Wayland session or enable X forwarding (e.g. ssh -X).\n"
        "Hint: in headless session you can point QT to real screen (find values in graphical session):\n"
        "`export DISPLAY=:0; export WAYLAND_DISPLAY=wayland-0; export XDG_SESSION_TYPE=wayland`"
    )


def connect_to_libvirt() -> libvirt.virConnect:
    """Establish a connection to libvirt, failing fast if unsuccessful."""
    # conn = libvirt.open("qemu:///system")
    conn = libvirt.open("test:///default")
    assert conn is not None, "Failed to open libvirt connection. Ensure libvirtd is running and permissions are set."
    return conn


def get_vms(conn: libvirt.virConnect) -> List[VMInfo]:
    """Retrieve list of VMs with their statuses, using assertions for preconditions."""
    assert conn.isAlive(), "Libvirt connection is not alive."
    domains = conn.listAllDomains()
    vms: List[VMInfo] = []
    for domain in domains:
        status = "running" if domain.isActive() else "shut off"
        vms.append(VMInfo(name=domain.name(), status=status, domain=domain))
    # Postcondition: Ensure we have at least one VM or handle empty list gracefully in UI
    return vms


def start_vm(domain: libvirt.virDomain) -> None:
    """Start a VM, handling errors gracefully."""
    try:
        domain.create()
    except libvirt.libvirtError as e:
        QMessageBox.critical(None, "Error", f"Failed to start VM: {str(e)}")


def stop_vm(domain: libvirt.virDomain) -> None:
    """Stop a VM, handling errors gracefully."""
    try:
        if domain.isActive():
            domain.destroy()
    except libvirt.libvirtError as e:
        QMessageBox.critical(None, "Error", f"Failed to stop VM: {str(e)}")


def build_menu(vms: List[VMInfo]) -> QMenu:
    """Build dynamic QMenu with VM names, statuses, and actions."""
    menu = QMenu()
    for vm in vms:
        # Create submenu for each VM
        vm_menu = menu.addMenu(f"{vm['name']} ({vm['status']})")

        if vm["status"] == "shut off":
            start_action = vm_menu.addAction("Start")
            start_action.triggered.connect(lambda _, d=vm["domain"]: start_vm(d))  # type: ignore[attr-defined]
        elif vm["status"] == "running":
            stop_action = vm_menu.addAction("Stop")
            stop_action.triggered.connect(lambda _, d=vm["domain"]: stop_vm(d))  # type: ignore[attr-defined]

    if not vms:
        menu.addAction("No VMs found")

    # Add quit action at the bottom
    menu.addSeparator()
    quit_action = menu.addAction("Quit")
    quit_action.triggered.connect(QApplication.instance().quit)  # type: ignore[attr-defined]

    return menu


def main() -> None:
    ensure_graphical_environment()

    app = QApplication(sys.argv)

    # Fail fast: Ensure tray is supported
    assert QSystemTrayIcon.isSystemTrayAvailable(), "System tray is not available on this platform."

    tray = QSystemTrayIcon()
    tray.setIcon(QIcon.fromTheme("virtual-machine"))  # Use system theme icon; falls back gracefully
    tray.setVisible(True)

    # Establish libvirt connection early
    conn = connect_to_libvirt()

    # Function to update menu on poll
    def update_menu() -> None:
        try:
            vms = get_vms(conn)
            menu = build_menu(vms)
            tray.setContextMenu(menu)
        except Exception as e:  # Graceful handling of unexpected errors
            QMessageBox.critical(None, "Error", f"Failed to update VM status: {str(e)}")

    # Initial menu setup
    update_menu()

    # Set up polling with QTimer (every 10 seconds)
    # Comment: QTimer is used for periodic updates without blocking the Qt event loop.
    timer = QTimer()
    timer.timeout.connect(update_menu)  # type: ignore[attr-defined]
    timer.start(10000)  # 10 seconds

    # Comment: Libvirt event handling could be added here for more efficiency, but polling is simple and sufficient for minimalism.

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
