# NexFault – Host‑Side Software

This repository contains the host‑side software for **NexFault One**, providing serial monitoring and control interfaces for the UUT (Unit Under Test) and DSI (Device Support Interface).

---

## Prerequisites

Before installing or running the NexFault host software, ensure the following are available on your system:

- **Python 3.9+**
- **Git**
- **NexFault hardware kit**
  - Flashed with the latest firmware

> No additional system packages are required. All Python dependencies are installed automatically.

---

## Installation

From the `host-side` directory, run the setup script:

```bash
python setup/setup.py
```

The setup process will:

- Upgrade `pip` if necessary
- Install all required Python dependencies
- Initialize and update the protobuf Git submodule

---

## Running the Application

### Run both serial monitors (recommended)

To launch **both the UUT and DSI serial monitors simultaneously**, run:

```bash
python run.py
```

This will open both GUI applications in parallel.

---

### Run individual monitors

You may also run either monitor independently using Python’s module execution:

```bash
python -m nexfault.gui.DSI_Serial_Monitor
```

```bash
python -m nexfault.gui.UUT_Serial_Monitor
```

---

## Project Structure (Host‑Side)

```text
host-side/
├─ nexfault/          # NexFault Python package
├─ setup/             # Setup and dependency installation
│  ├─ setup.py
│  └─ requirements.txt
├─ run.py             # Launches both serial monitors
├─ .gitmodules
└─ .gitignore
```

---

## Notes

- The application is cross‑platform and supported on **Windows, macOS, and Linux**
- Python dependencies (including protobuf) are managed via `requirements.txt`
- The required protobuf runtime is included via submodule

---

## Troubleshooting

- Ensure Python is available on your PATH:
  ```bash
  python --version
  ```
- Ensure Git is installed and accessible:
  ```bash
  git --version
  ```
- If setup fails, re‑run:
  ```bash
  python setup/setup.py
  ```
