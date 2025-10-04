import asyncio
import logging
import os
import sys
from collections.abc import Awaitable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypedDict

import libvirt  # type: ignore[reportMissingTypeStubs, attr-defined]
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PyQt6.QtWidgets import QMenu, QMessageBox, QStyle, QSystemTrayIcon
from qasync import QApplication, QEventLoop, asyncSlot


IS_TEST: bool = os.getenv("TEST") is not None and os.getenv("TEST") != ""
TEST_CONNECTION = f"test://{Path('tests/libvirt-test-setup.xml').resolve()}"
DEFAULT_CONNECTION = "qemu:///system"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
BASE_ICON_FILE = ASSETS_DIR / "vm_tray_base.svg"
POLL_INTERVAL_SECONDS: int = 10

LOGGER = logging.getLogger(__name__)


# Define typed structure for VM information
class VMInfo(TypedDict):
    name: str
    status: str
    domain: libvirt.virDomain


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
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
        "Detected DISPLAY=%s WAYLAND_DISPLAY=%s",
        vars_to_check.get("DISPLAY"),
        vars_to_check.get("WAYLAND_DISPLAY"),
    )
    assert has_x11 or has_wayland, (
        "No graphical display detected. Run inside an X11/Wayland session or enable X forwarding (e.g. ssh -X).\n"
        "Hint: in headless session you can point QT to real screen (find values in graphical session):\n"
        "`export DISPLAY=:0; export WAYLAND_DISPLAY=wayland-0; export XDG_SESSION_TYPE=wayland`"
    )


def connect_to_libvirt() -> libvirt.virConnect:
    """Establish a connection to libvirt, failing fast if unsuccessful."""
    conn = libvirt.open(TEST_CONNECTION if IS_TEST else DEFAULT_CONNECTION)
    LOGGER.info(
        "Libvirt connection opened",
        extra={"endpoint": TEST_CONNECTION if IS_TEST else DEFAULT_CONNECTION},
    )
    assert (
        conn is not None
    ), "Failed to open libvirt connection. Ensure libvirtd is running and permissions are set."
    return conn


def _get_vms_sync(conn: libvirt.virConnect) -> list[VMInfo]:
    """Synchronous VM retrieval - runs in executor to avoid blocking event loop."""
    assert conn.isAlive(), "Libvirt connection is not alive."
    LOGGER.debug("Fetching domains from libvirt")
    domains = conn.listAllDomains()
    vms: list[VMInfo] = []
    for domain in domains:
        status = "running" if domain.isActive() else "shut off"
        vms.append(VMInfo(name=domain.name(), status=status, domain=domain))
    LOGGER.info("Retrieved %s VM(s)", len(vms))
    return vms


async def get_vms(
    conn: libvirt.virConnect, executor: ThreadPoolExecutor
) -> list[VMInfo]:
    """Retrieve list of VMs asynchronously without blocking the event loop."""
    loop = asyncio.get_running_loop()
    vms = await loop.run_in_executor(executor, _get_vms_sync, conn)
    return vms


def _start_vm_sync(domain: libvirt.virDomain) -> None:
    """Synchronous VM start - runs in executor."""
    LOGGER.info("Starting VM", extra={"vm": domain.name()})
    domain.create()
    LOGGER.debug("VM start completed", extra={"vm": domain.name()})


async def start_vm(domain: libvirt.virDomain, executor: ThreadPoolExecutor) -> None:
    """Start a VM asynchronously, handling errors gracefully."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(executor, _start_vm_sync, domain)
    except libvirt.libvirtError as e:
        QMessageBox.critical(None, "Error", f"Failed to start VM: {str(e)}")
        LOGGER.exception("Failed to start VM", extra={"vm": domain.name()})


def _stop_vm_sync(domain: libvirt.virDomain) -> None:
    """Synchronous VM stop - runs in executor."""
    if domain.isActive():
        LOGGER.info("Stopping VM", extra={"vm": domain.name()})
        domain.destroy()
        LOGGER.debug("VM stop completed", extra={"vm": domain.name()})


async def stop_vm(domain: libvirt.virDomain, executor: ThreadPoolExecutor) -> None:
    """Stop a VM asynchronously, handling errors gracefully."""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(executor, _stop_vm_sync, domain)
    except libvirt.libvirtError as e:
        QMessageBox.critical(None, "Error", f"Failed to stop VM: {str(e)}")
        LOGGER.exception("Failed to stop VM", extra={"vm": domain.name()})


def _make_async_trigger(
    handler: Callable[[libvirt.virDomain, ThreadPoolExecutor], Awaitable[None]],
    domain: libvirt.virDomain,
    executor: ThreadPoolExecutor,
) -> Callable[[bool], None]:
    """Create a slot trigger that schedules async handler without blocking."""

    @asyncSlot()
    async def trigger(_checked: bool) -> None:
        await handler(domain, executor)

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
            LOGGER.warning(
                "Path override exists but icon is null", extra={"path": str(path)}
            )

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
        LOGGER.warning(
            "Bundled asset icon missing or invalid", extra={"path": str(BASE_ICON_FILE)}
        )

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
    highlight = (
        palette.color(QPalette.ColorRole.Highlight)
        if palette is not None
        else QColor(Qt.GlobalColor.green)
    )
    color = QColor(highlight)
    color.setAlpha(230)
    painter.setBrush(color)
    painter.setPen(Qt.PenStyle.NoPen)
    center_x = width - radius - margin
    center_y = radius + margin
    painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
    painter.end()

    return QIcon(pixmap)


def build_menu(vms: list[VMInfo], executor: ThreadPoolExecutor) -> QMenu:
    """Build dynamic QMenu with VM names, statuses, and async actions."""
    menu = QMenu()
    for vm in vms:
        vm_menu = menu.addMenu(f"{vm['name']} ({vm['status']})")
        assert vm_menu is not None, "Failed to create VM submenu"

        if vm["status"] == "shut off":
            start_action = vm_menu.addAction("Start")
            assert start_action is not None, "Failed to create start action"
            start_action.triggered.connect(
                _make_async_trigger(start_vm, vm["domain"], executor)
            )
        elif vm["status"] == "running":
            stop_action = vm_menu.addAction("Stop")
            assert stop_action is not None, "Failed to create stop action"
            stop_action.triggered.connect(
                _make_async_trigger(stop_vm, vm["domain"], executor)
            )

    if not vms:
        placeholder = menu.addAction("No VMs found")
        assert placeholder is not None, "Failed to create placeholder action"
        LOGGER.info("No VMs found during menu build")

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


async def periodic_menu_update(
    tray: QSystemTrayIcon,
    conn: libvirt.virConnect,
    base_icon: QIcon,
    running_icon: QIcon,
    executor: ThreadPoolExecutor,
) -> None:
    """Periodically update the tray menu without blocking the event loop."""
    while True:
        try:
            LOGGER.debug("Refreshing tray menu")
            vms = await get_vms(conn, executor)
            menu = build_menu(vms, executor)
            tray.setContextMenu(menu)
            any_running = any(vm["status"] == "running" for vm in vms)
            tray.setIcon(running_icon if any_running else base_icon)
            LOGGER.info(
                "Menu updated", extra={"running": any_running, "vm_count": len(vms)}
            )
        except Exception:
            tray.setIcon(base_icon)
            QMessageBox.critical(None, "Error", "Failed to update VM status")
            LOGGER.exception("Failed to refresh tray menu")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def async_main() -> None:
    """Main async entry point for the application."""
    configure_logging()
    LOGGER.info("VM tray starting")
    ensure_graphical_environment()

    print("-----Test mode-----" if IS_TEST else "Production mode")

    app = QApplication.instance()
    assert app is not None, "QApplication instance not found"

    # Fail fast: Ensure tray is supported
    assert (
        QSystemTrayIcon.isSystemTrayAvailable()
    ), "System tray is not available on this platform."

    tray = QSystemTrayIcon()
    base_icon = resolve_tray_icon(app)
    running_icon = icon_with_running_indicator(base_icon, app)
    tray.setIcon(base_icon)
    tray.setVisible(True)
    LOGGER.info("Tray icon initialized")

    # Establish libvirt connection
    conn = connect_to_libvirt()

    # Create thread pool executor for blocking libvirt calls
    executor = ThreadPoolExecutor(max_workers=4)
    LOGGER.debug("ThreadPoolExecutor initialized", extra={"max_workers": 4})

    # Initial menu setup
    try:
        vms = await get_vms(conn, executor)
        menu = build_menu(vms, executor)
        tray.setContextMenu(menu)
        any_running = any(vm["status"] == "running" for vm in vms)
        tray.setIcon(running_icon if any_running else base_icon)
        LOGGER.info(
            "Initial menu set", extra={"running": any_running, "vm_count": len(vms)}
        )
    except Exception:
        LOGGER.exception("Failed to set initial menu")

    # Start periodic update task
    update_task = asyncio.create_task(
        periodic_menu_update(tray, conn, base_icon, running_icon, executor)
    )
    LOGGER.debug(
        "Periodic update task started",
        extra={"interval_seconds": POLL_INTERVAL_SECONDS},
    )

    # Wait for app quit signal
    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)  # type: ignore[attr-defined]

    await app_close_event.wait()

    # Cleanup
    update_task.cancel()
    try:
        await update_task
    except asyncio.CancelledError:
        pass
    executor.shutdown(wait=True)
    conn.close()
    LOGGER.info("VM tray shutting down")


def main() -> None:
    """Entry point that sets up qasync event loop and runs async main."""
    app = QApplication(sys.argv)

    # Modern Python 3.11+ approach with qasync
    try:
        asyncio.run(async_main(), loop_factory=lambda: QEventLoop(app))
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
        sys.exit(0)


if __name__ == "__main__":
    main()
