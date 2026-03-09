import subprocess
import sys
from pathlib import Path


def run_module(module_name, project_root):
    """Runs module using current interpreter"""
    command = [
        sys.executable,
        "-m",
        module_name,
    ]

    print("> " + " ".join(command))
    return subprocess.Popen(command, cwd=project_root)


def main():
    """Executes selected modules."""
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir

    modules = [
        "nexfault.gui.DSI_Serial_Monitor",
        "nexfault.gui.UUT_Serial_Monitor",
        "nexfault.gui.testbench",
    ]

    processes = []

    for module in modules:
        processes.append(run_module(module, project_root))


if __name__ == "__main__":
    main()
