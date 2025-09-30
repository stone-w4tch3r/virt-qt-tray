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
```

