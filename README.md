# Description

A simple tray application for managing libvirt virtual machines.

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
TEST=1 uv run src/main.py # use fake libvirt connection
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
