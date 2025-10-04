# Description

A simple tray application for managing libvirt virtual machines.

## Icon Customisation

- The tray icon follows freedesktop theming first. Set `VM_TRAY_ICON_NAME` to pick any installed icon name (for example `vm-tray`).
- Provide a direct asset with `VM_TRAY_ICON_PATH=/path/to/icon.png` or drop a replacement SVG/PNG into the desktop icon theme; the bundled fallback lives at `assets/vm_tray_base.svg`.
- When any VM is running the app paints a small highlight dot onto the icon so you have a quick status indicator across dark/light panels.
- Because the app resolves the icon at runtime, you can ship distro-specific artwork without touching the codebase.

# Dev setup

## Using Distrobox (Recommended)

```bash
distrobox-assemble create --file distrobox.ini
```

**Run the application:**
```bash
# Fix D-Bus connection for system tray (once)
distrobox enter fedora-dev -- bash -c 'sudo rm -f /run/user/1000/bus && sudo ln -s /run/host/run/user/1000/bus /run/user/1000/bus'

# Run the application
distrobox enter fedora-dev -- uv sync
distrobox enter fedora-dev -- uv run src/main.py
```

**Test mode (fake libvirt)**
```bash
TEST=1 uv run src/main.py # use fake libvirt connection
```

## Host Deps Installation

**Ubuntu:**
```bash
sudo apt install gcc libvirt-dev python3-dev pipx -y # and maybe smth else
pipx ensurepath && pipx install uv
```

**Fedora:**
```bash
sudo dnf install uv gcc libvirt-devel -y # and maybe smth else
```

**Then:**
```bash
uv sync
uv run src/main.py
```


## Running via SSH

When running the application via SSH, you need to set the proper environment variables to access the graphical display:

```bash
# Get actual values from graphical session
export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_SESSION_TYPE=wayland
uv run src/main.py
```

This allows the PyQt application to connect to the VM's desktop session and display on the VM screen.
