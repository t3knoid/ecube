# ECUBE Debugging Guide

**Version:** 1.0  
**Last Updated:** March 2026  
**Audience:** Developers, Contributors  
**Document Type:** How-To

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [VS Code Extension](#vs-code-extension)
3. [Quickstart Debugging (Command Line)](#quickstart-debugging-command-line)
4. [Debugging in VS Code](#debugging-in-vs-code)
5. [Debugging Tests](#debugging-tests)
6. [Tips and Troubleshooting](#tips-and-troubleshooting)

---

## Prerequisites

Follow the [Development Guide](00-development-guide.md) to set up your environment first. Ensure you have:

- Python 3.11+ with a virtual environment activated
- The project installed in editable mode: `pip install -e ".[dev]"`
- PostgreSQL running (Docker or local) if debugging against a real database

---

## VS Code Extension

Install the **Python** extension by Microsoft:

- **Extension ID:** `ms-python.python`
- **Install from VS Code:** Open the Extensions view (`Ctrl+Shift+X` / `Cmd+Shift+X`), search for **Python**, and install the one published by **Microsoft**.
- **Marketplace:** https://marketplace.visualstudio.com/items?itemName=ms-python.python

This extension provides:

- Integrated debugger with breakpoints, watch variables, and call stack
- Launch configuration support for FastAPI/Uvicorn and pytest
- Python environment detection (selects your `.venv` automatically)
- IntelliSense, linting, and test discovery

> **Tip:** After installing, open the Command Palette (`Ctrl+Shift+P` / `Cmd+Shift+P`) and run **Python: Select Interpreter**, then choose the `.venv` interpreter in the workspace.

---

## Quickstart Debugging (Command Line)

These approaches work on any platform without an IDE.

### 1. Verbose Pytest Output

Run tests with increased verbosity and print output enabled:

```bash
# Show full assertion diffs and print() output
python -m pytest tests/test_drives.py -v -s

# Stop on first failure
python -m pytest tests/test_drives.py -v -s -x

# Run a single test by name
python -m pytest tests/test_drives.py -v -s -k "test_list_drives"
```

| Flag | Purpose |
|------|---------|
| `-v` | Verbose — show each test name and result |
| `-s` | Disable output capture — `print()` statements appear in the terminal |
| `-x` | Stop on first failure |
| `-k "expr"` | Run only tests matching the expression |
| `--tb=short` | Shorter traceback format |
| `--tb=long` | Full traceback with local variables |

### 2. Python Debugger (pdb)

Insert a breakpoint anywhere in application or test code:

```python
breakpoint()  # Drops into pdb at this line
```

Then run the test (or server) normally. When execution hits the breakpoint, you get an interactive prompt:

```bash
python -m pytest tests/test_drives.py -v -s -k "test_list_drives"
```

Common pdb commands:

| Command | Action |
|---------|--------|
| `n` | Step to the next line |
| `s` | Step into a function call |
| `c` | Continue execution until the next breakpoint |
| `p expr` | Print the value of an expression |
| `pp expr` | Pretty-print the value |
| `l` | Show source code around the current line |
| `ll` | Show the full source of the current function |
| `w` | Show the call stack |
| `q` | Quit the debugger |

> **Important:** Remember to remove `breakpoint()` calls before committing.

### 3. Debugging the Running Server

Start Uvicorn with `--reload` and use `breakpoint()` in endpoint handlers or service code:

```bash
uvicorn app.main:app --reload
```

When a request hits the breakpoint, the terminal drops into pdb. The request will block until you continue (`c`) or quit (`q`).

### 4. Logging

ECUBE uses Python's `logging` module. Increase verbosity temporarily:

```bash
# Set log level via environment variable
LOG_LEVEL=DEBUG uvicorn app.main:app --reload
```

Or add debug logging in code:

```python
import logging
logger = logging.getLogger(__name__)
logger.debug("drive_id=%s, state=%s", drive.id, drive.state)
```

---

## Debugging in VS Code

The workspace includes a `.vscode/launch.json` with pre-configured debug targets. You can also add your own.

### Existing Launch Configurations

Open the **Run and Debug** panel (`Ctrl+Shift+D` / `Cmd+Shift+D`) to see these configurations:

| Configuration | Description |
|---------------|-------------|
| **Pytest: Integration (all)** | Runs all integration tests in `tests/integration/` with `--run-integration` against the PostgreSQL test database |
| **Pytest: Integration (current file)** | Runs integration tests in the currently open file |

Both integration configurations set `DATABASE_URL` to the test PostgreSQL instance at `localhost:5433`.

### Adding a FastAPI Server Debug Configuration

To debug the running API server with breakpoints, add this configuration to `.vscode/launch.json`:

```json
{
    "name": "ECUBE: FastAPI Server",
    "type": "python",
    "request": "launch",
    "module": "uvicorn",
    "args": [
        "app.main:app",
        "--reload",
        "--port", "8000"
    ],
    "cwd": "${workspaceFolder}",
    "env": {
        "DATABASE_URL": "postgresql://ecube:ecube@localhost/ecube"
    },
    "console": "integratedTerminal",
    "justMyCode": false
}
```

> **Note:** Set `"justMyCode": false` if you want to step into library code (FastAPI, SQLAlchemy, etc.). Set it to `true` to stay within the ECUBE codebase.

### Adding a Unit Test Debug Configuration

To debug unit tests (SQLite in-memory, no PostgreSQL required):

```json
{
    "name": "Pytest: Unit (current file)",
    "type": "python",
    "request": "launch",
    "module": "pytest",
    "cwd": "${workspaceFolder}",
    "args": [
        "${file}",
        "-v",
        "-s"
    ],
    "console": "integratedTerminal",
    "justMyCode": true
},
{
    "name": "Pytest: Unit (all)",
    "type": "python",
    "request": "launch",
    "module": "pytest",
    "cwd": "${workspaceFolder}",
    "args": [
        "tests/",
        "-v",
        "-s"
    ],
    "console": "integratedTerminal",
    "justMyCode": true
}
```

### Setting Breakpoints

1. Open any Python file in the editor.
2. Click in the gutter to the left of a line number — a red dot appears.
3. Start a debug configuration from the **Run and Debug** panel.
4. Execution pauses at the breakpoint. Use the **Debug toolbar** or these shortcuts:

| Action | Shortcut (macOS) | Shortcut (Windows/Linux) |
|--------|-------------------|--------------------------|
| Continue | `F5` | `F5` |
| Step Over | `F10` | `F10` |
| Step Into | `F11` | `F11` |
| Step Out | `Shift+F11` | `Shift+F11` |
| Restart | `Cmd+Shift+F5` | `Ctrl+Shift+F5` |
| Stop | `Shift+F5` | `Shift+F5` |

### Conditional Breakpoints

Right-click a breakpoint and select **Edit Breakpoint** to add a condition:

- **Expression:** e.g., `drive.state == "IN_USE"` — pauses only when the condition is true.
- **Hit Count:** e.g., `5` — pauses on the 5th hit.
- **Log Message:** e.g., `drive_id={drive.id} state={drive.state}` — prints to the Debug Console without pausing (logpoint).

### Using the Debug Console

While paused at a breakpoint, the **Debug Console** (`Ctrl+Shift+Y` / `Cmd+Shift+Y`) lets you evaluate Python expressions in the current scope:

```
>>> drive.state
'AVAILABLE'
>>> db.query(UsbDrive).count()
3
>>> response.json()
{'drives': [...]}
```

### Debugging a Single Test from the Editor

With the Python extension installed, test files show **Run Test** and **Debug Test** icons (play and bug icons) above each test function and class. Click the bug icon to launch the debugger for that single test — no launch configuration needed.

---

## Tips and Troubleshooting

### Wrong Python Interpreter

If imports fail or breakpoints are not hit, verify the interpreter:

1. Open Command Palette → **Python: Select Interpreter**
2. Choose the `.venv` interpreter in the workspace root

### Breakpoints Not Hit (Server)

- Ensure you started the server via the VS Code debug configuration, not from a separate terminal.
- If using `--reload`, Uvicorn spawns a child process. The debugger attaches to the parent. Breakpoints may not fire until you remove `--reload` from the launch args or set `"justMyCode": false`.

### Tests Use SQLite, Server Uses PostgreSQL

Unit tests always use an in-memory SQLite database (see `tests/conftest.py`). If you are debugging a test and see unexpected SQL behavior, remember that SQLite has different semantics from PostgreSQL for features like `JSONB`, array types, and certain constraint behaviors.

### Integration Test Database

The integration test configurations expect PostgreSQL at `localhost:5433`. Start it with:

```bash
docker compose -f docker-compose.ecube.yml up -d postgres
```

### Viewing SQL Queries

Enable SQLAlchemy echo mode to see all generated SQL:

```python
# Temporarily in code
engine = create_engine(url, echo=True)
```

Or set the environment variable:

```bash
SQLALCHEMY_ECHO=true uvicorn app.main:app --reload
```

---

**End of Debugging Guide**
