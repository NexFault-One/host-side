import platform
import subprocess
import sys
from pathlib import Path

def run(cmd):
    subprocess.check_call(cmd, shell=True)

def main():
    """Installs NexFault One dependencies and submodules"""
    script_dir = Path(__file__).resolve().parent
    requirements = script_dir / "requirements.txt"
    repo_root = script_dir.parent

    print("OS:", platform.system())
    run(f"{sys.executable} -m pip install --upgrade pip")
    run(f"{sys.executable} -m pip install -r \"{requirements}\"")

    output = subprocess.check_call(
        ["git", "submodule", "update", "--init", "--recursive"],
        cwd=repo_root,
        text=True
    )

    print("Installation complete.")
    print("Run the tool with: python run.py")

if __name__ == "__main__":
    main()