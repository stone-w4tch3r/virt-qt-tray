# VM Tray App Project Description

## Project Overview
This project is a minimal system tray application for monitoring and controlling libvirt-managed virtual machines (VMs) on Linux systems. It provides a simple tray icon with a context menu listing VMs (created via tools like virt-manager), their status (e.g., running or stopped), and basic actions (start, stop). The app polls libvirt periodically for updates and is designed to be cross-compatible across Linux desktop environments (e.g., GNOME, KDE, XFCE) with a native look using Qt styling.

### Key Features
- Tray icon with dynamic menu showing VM names and statuses.
- Actions to start or stop VMs.
- Periodic polling (e.g., every 10 seconds) for real-time status updates.
- Error handling for libvirt connections and permissions.
- Cross-Linux compatibility, adhering to standards like XDG Base Directory Specification for any future config needs (e.g., icon paths or user data).

### Technical Task
- **Language and Version**: Python 3.12.
- **Dependencies**: PyQt6 (for tray and menu UI), libvirt-python (for VM interactions).
- **Tools**:
  - **uv**: For fast dependency management, virtual environment handling, and project building (replaces pip/Poetry for speed).
  - **Ruff**: For code linting, formatting, and style enforcement (configured for modern Python best practices).
  - **Basedpyright**: For static type checking at the "recommended" level (stricter than default pyright).
  - **Pytest**: For unit testing.
- **Best Practices**:
  - **Fail Fast**: Use assertions and preconditions to raise errors early (e.g., check libvirt connection on startup).
  - **Type Safety**: Full type hints using `typing` module; prefer `TypedDict` over untyped dicts; avoid `**kwargs` by using explicit parameters.
  - **Code Quality**: Well-commented code (focus on explaining logic, not every line); pre/postcondition checks via assertions.
  - **Robustness**: No untyped data structures; handle exceptions gracefully; use XDG standards for paths (e.g., via `xdg` library if configs are added later).
  - **Minimalism**: Keep the project small (1-2 source files) while including tests and configs.
- **Complexity**: This is a single-file core app with modular structure for extensibility. It fits into a small script but is organized as a package for better practices.
- **Setup Instructions**:
  1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
  2. Create and activate venv: `uv venv`.
  3. Install dependencies: `uv sync`.
  4. Run type checks: `uv run basedpyright .`.
  5. Lint: `uv run ruff check --fix .` and `uv run ruff format .`.
  6. Run tests: `uv run pytest`.
  7. Run app: `uv run python -m vm_tray`.

## Code Structure
The project follows a modern Python package structure for clarity, testability, and reusability, inspired by best practices (e.g., src layout for separation of concerns). It's minimal: core logic in one main module, with tests in a separate directory. This allows easy extension (e.g., adding more features) without bloat.

- **src/vm_tray/**: Package directory containing the application code.
  - Main entry point handles tray setup, menu building, and polling.
  - Libvirt interactions are encapsulated in functions with type hints and assertions.
- **tests/**: Unit tests for key functions (e.g., mocking libvirt connections).
- Configuration files at root for dependency management, linting, and type checking.
- No unnecessary nesting; flat structure for simplicity.
- **Fail Fast and Preconditions**: Assertions check inputs/outputs (e.g., ensure libvirt connection succeeds or raise early).
- **Type Safety**: All functions use type hints; data like VM info uses TypedDict.
- **Comments**: Placed strategically to explain libvirt quirks or Qt event handling, not trivial lines.
- **XDG Compatibility**: If icons or configs are used, paths follow XDG (e.g., via `os.environ.get('XDG_DATA_HOME')`).

### File List and Descriptions
Here's the minimal set of files:

```
vm_tray/
├── pyproject.toml          # Project metadata, dependencies, and tool configs (e.g., ruff, basedpyright).
├── uv.lock                 # Locked dependencies (generated via uv).
├── AGENTS.md               # This document (project description and instructions).
├── .gitignore              # Ignores venv, pyc files, etc.
├── ruff.toml               # Ruff configuration for linting and formatting.
├── basedpyright.toml       # Basedpyright config at "recommended" level.
├── src/
│   └── vm_tray/
│       ├── __init__.py     # Empty package init.
│       └── main.py         # Core app: tray setup, libvirt polling, menu building.
└── tests/
    ├── __init__.py         # Empty init for test discovery.
    └── test_main.py        # Unit tests for main functions (e.g., mock libvirt, test menu logic).
```

- **pyproject.toml**: Defines project name, version, dependencies (PyQt6, libvirt-python, pytest for dev). Includes [tool.ruff] and [tool.basedpyright] sections for configs.
- **ruff.toml**: Configures rules like line length=120, enable modern Python features, enforce type hints.
- **basedpyright.toml**: Sets strictness to "recommended"
- **src/vm_tray/main.py**: Single file with:
  - Imports: Typed and minimal. Untyped imports suppressed.
  - Functions: e.g., `get_vm_status(conn: libvirt.virConnect) -> list[TypedDict('VMInfo', {'name': str, 'status': str})]` with assertions.
  - Main: Sets up QApplication, QSystemTrayIcon, QTimer for polling, and dynamic QMenu.
  - Comments: Explain libvirt connection handling and Qt signal connections.
- **tests/test_main.py**: Uses pytest with mocks (e.g., unittest.mock for libvirt) to test functions like VM listing and actions. Includes pre/postcondition assertions in tests.
