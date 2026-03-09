import platform
import subprocess
import sys
from pathlib import Path


def run(cmd):
    subprocess.check_call(cmd, shell=True)


def main():
    """Installs NexFault One dependencies and submodules"""
    repo_root = Path(__file__).resolve().parent
    requirements = repo_root / "requirements.txt"

    print("OS:", platform.system())
    run(f"{sys.executable} -m pip install --upgrade pip")
    run(f'{sys.executable} -m pip install -r "{requirements}"')

    subprocess.check_call(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=repo_root,
        text=True,
    )

    print("Installation complete.")
    print("Run the tool with: python run.py")


if __name__ == "__main__":
    main()
