# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, TypedDict

import libvirt  # type: ignore[reportMissingTypeStubs, attr-defined]
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QStyle, QSystemTrayIcon

IS_TEST: bool = os.getenv("TEST") is not None and os.getenv("TEST") != ""
TEST_CONNECTION = f"test://{Path('tests/libvirt-test-setup.xml').resolve()}"
DEFAULT_CONNECTION = "qemu:///system"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BASE_ICON_FILE = ASSETS_DIR / "vm_tray_base.svg"

LOGGER = logging.getLogger(__name__)


# Define typed structure for VM information
class VMInfo(TypedDict):
    name: str
    status: str
    domain: libvirt.virDomain


def configure_logging() -> None:
    level_name = os.getenv("VM_TRAY_LOG_LEVEL", "INFO").upper()
    level = logging.getLevelName(level_name)
    if not isinstance(level, int):
        level = logging.INFO

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    root_logger.setLevel(level)
    LOGGER.debug("Logging configured", extra={"level": logging.getLevelName(level)})


def ensure_graphical_environment(env: Mapping[str, str] | None = None) -> None:
    """Fail fast when no GUI session is available (e.g. plain SSH)."""
    vars_to_check = env if env is not None else os.environ
    has_x11 = bool(vars_to_check.get("DISPLAY"))
    has_wayland = bool(vars_to_check.get("WAYLAND_DISPLAY"))
    LOGGER.debug(
        "Detected DISPLAY=%s WAYLAND_DISPLAY=%s", vars_to_check.get("DISPLAY"), vars_to_check.get("WAYLAND_DISPLAY")
    )
    assert has_x11 or has_wayland, (
        "No graphical display detected. Run inside an X11/Wayland session or enable X forwarding (e.g. ssh -X).\n"
        "Hint: in headless session you can point QT to real screen (find values in graphical session):\n"
        "`export DISPLAY=:0; export WAYLAND_DISPLAY=wayland-0; export XDG_SESSION_TYPE=wayland`"
    )


def connect_to_libvirt() -> libvirt.virConnect:
    """Establish a connection to libvirt, failing fast if unsuccessful."""
    conn = libvirt.open(TEST_CONNECTION if IS_TEST else DEFAULT_CONNECTION)
    LOGGER.info("Libvirt connection opened", extra={"endpoint": TEST_CONNECTION if IS_TEST else DEFAULT_CONNECTION})
    assert conn is not None, "Failed to open libvirt connection. Ensure libvirtd is running and permissions are set."
    return conn


def get_vms(conn: libvirt.virConnect) -> list[VMInfo]:
    """Retrieve list of VMs with their statuses, using assertions for preconditions."""
    assert conn.isAlive(), "Libvirt connection is not alive."
    LOGGER.debug("Fetching domains from libvirt")
    domains = conn.listAllDomains()
    vms: list[VMInfo] = []
    for domain in domains:
        status = "running" if domain.isActive() else "shut off"
        vms.append(VMInfo(name=domain.name(), status=status, domain=domain))
    LOGGER.info("Retrieved %s VM(s)", len(vms))
    # Postcondition: Ensure we have at least one VM or handle empty list gracefully in UI
    return vms


def start_vm(domain: libvirt.virDomain) -> None:
    """Start a VM, handling errors gracefully."""
    try:
        LOGGER.info("Starting VM", extra={"vm": domain.name()})
        domain.create()
        LOGGER.debug("VM start requested", extra={"vm": domain.name()})
    except libvirt.libvirtError as e:
        QMessageBox.critical(None, "Error", f"Failed to start VM: {str(e)}")
        LOGGER.exception("Failed to start VM", extra={"vm": domain.name()})


def stop_vm(domain: libvirt.virDomain) -> None:
    """Stop a VM, handling errors gracefully."""
    try:
        if domain.isActive():
            LOGGER.info("Stopping VM", extra={"vm": domain.name()})
            domain.destroy()
            LOGGER.debug("VM stop requested", extra={"vm": domain.name()})
    except libvirt.libvirtError as e:
        QMessageBox.critical(None, "Error", f"Failed to stop VM: {str(e)}")
        LOGGER.exception("Failed to stop VM", extra={"vm": domain.name()})


def _make_trigger(handler: Callable[[libvirt.virDomain], None], domain: libvirt.virDomain) -> Callable[[bool], None]:
    def trigger(_checked: bool) -> None:
        handler(domain)

    return trigger


def resolve_tray_icon(app: QApplication) -> QIcon:
    """Resolve a themed tray icon with fallbacks per freedesktop guidance."""
    path_override = os.getenv("VM_TRAY_ICON_PATH")
    if path_override:
        path = Path(path_override).expanduser()
        if path.exists():
            file_icon = QIcon(str(path))
            if not file_icon.isNull():
                LOGGER.info("Using icon from path override", extra={"path": str(path)})
                return file_icon
            LOGGER.warning("Path override exists but icon is null", extra={"path": str(path)})

    icon_candidates = [
        os.getenv("VM_TRAY_ICON_NAME"),
        "vm-tray",
        "virt-manager",
        "virtual-machine",
    ]

    for name in icon_candidates:
        if not name:
            continue
        themed_icon = QIcon.fromTheme(name)
        if not themed_icon.isNull():
            LOGGER.info("Using themed icon", extra={"icon": name})
            return themed_icon
        LOGGER.debug("Theme icon not available", extra={"icon": name})

    if BASE_ICON_FILE.exists():
        asset_icon = QIcon(str(BASE_ICON_FILE))
        if not asset_icon.isNull():
            LOGGER.info("Using bundled asset icon", extra={"path": str(BASE_ICON_FILE)})
            return asset_icon
        LOGGER.warning("Bundled asset icon missing or invalid", extra={"path": str(BASE_ICON_FILE)})

    style = app.style()
    if style is not None:
        style_icon = style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        if not style_icon.isNull():
            LOGGER.info("Using style icon fallback")
            return style_icon
        LOGGER.debug("Style icon fallback returned null")

    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.darkGray)
    LOGGER.info("Using generated fallback pixmap icon")
    return QIcon(pixmap)


def icon_with_running_indicator(base_icon: QIcon, app: QApplication) -> QIcon:
    """Overlay a status indicator dot to highlight running VMs."""
    style = app.style()
    size = style.pixelMetric(QStyle.PixelMetric.PM_ToolBarIconSize) if style else 32
    size = max(size, 24)
    pixmap = base_icon.pixmap(size, size)
    if pixmap.isNull():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.darkGray)

    pixmap = pixmap.copy()
    width = pixmap.width()
    radius = max(3, width // 6)
    margin = max(2, width // 12)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    palette = app.palette() if app else None
    highlight = palette.color(QPalette.ColorRole.Highlight) if palette is not None else QColor(Qt.GlobalColor.green)
    color = QColor(highlight)
    color.setAlpha(230)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    center_x = width - radius - margin
    center_y = radius + margin
    painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
    painter.end()

    return QIcon(pixmap)


def build_menu(vms: list[VMInfo]) -> QMenu:
    """Build dynamic QMenu with VM names, statuses, and actions."""
    menu = QMenu()
    for vm in vms:
        # Create submenu for each VM
        vm_menu = menu.addMenu(f"{vm['name']} ({vm['status']})")
        assert vm_menu is not None, "Failed to create VM submenu"

        if vm["status"] == "shut off":
            start_action = vm_menu.addAction("Start")
            assert start_action is not None, "Failed to create start action"
            start_action.triggered.connect(_make_trigger(start_vm, vm["domain"]))
        elif vm["status"] == "running":
            stop_action = vm_menu.addAction("Stop")
            assert stop_action is not None, "Failed to create stop action"
            stop_action.triggered.connect(_make_trigger(stop_vm, vm["domain"]))

    if not vms:
        placeholder = menu.addAction("No VMs found")
        assert placeholder is not None, "Failed to create placeholder action"
        LOGGER.info("No VMs found during menu build")

    # Add quit action at the bottom
    menu.addSeparator()
    quit_action = menu.addAction("Quit")
    assert quit_action is not None, "Failed to create quit action"

    def handle_quit(_checked: bool) -> None:
        LOGGER.info("Quit requested from tray menu")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    quit_action.triggered.connect(handle_quit)

    return menu


def main() -> None:
    configure_logging()
    LOGGER.info("VM tray starting")
    ensure_graphical_environment()

    app = QApplication(sys.argv)

    # Fail fast: Ensure tray is supported
    assert QSystemTrayIcon.isSystemTrayAvailable(), "System tray is not available on this platform."

    tray = QSystemTrayIcon()
    base_icon = resolve_tray_icon(app)
    running_icon = icon_with_running_indicator(base_icon, app)
    tray.setIcon(base_icon)
    tray.setVisible(True)
    LOGGER.info("Tray icon initialised")

    # Establish libvirt connection early
    conn = connect_to_libvirt()

    # Function to update menu on poll
    def update_menu() -> None:
        try:
            LOGGER.debug("Refreshing tray menu")
            vms = get_vms(conn)
            menu = build_menu(vms)
            tray.setContextMenu(menu)
            any_running = any(vm["status"] == "running" for vm in vms)
            tray.setIcon(running_icon if any_running else base_icon)
            LOGGER.info("Menu updated", extra={"running": any_running, "vm_count": len(vms)})
        except Exception as e:  # Graceful handling of unexpected errors
            tray.setIcon(base_icon)
            QMessageBox.critical(None, "Error", f"Failed to update VM status: {str(e)}")
            LOGGER.exception("Failed to refresh tray menu")

    # Initial menu setup
    update_menu()

    # Set up polling with QTimer (every 10 seconds)
    # Comment: QTimer is used for periodic updates without blocking the Qt event loop.
    timer = QTimer()
    timer.timeout.connect(update_menu)  # type: ignore[attr-defined]
    timer.start(10000)  # 10 seconds
    LOGGER.debug("Polling timer started", extra={"interval_ms": 10000})

    # Comment: Libvirt event handling could be added here for more efficiency, but polling is simple and sufficient for minimalism.

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
