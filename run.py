import subprocess
import sys
import webbrowser
import time
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
    """Starts the NexFault backend and opens the web app."""
    project_root = Path(__file__).resolve().parent
    webapp_path = project_root / "web-app" / "webapp.html"

    processes = []

    # Start the FastAPI backend
    print("Starting NexFault backend...")
    backend = run_module("nexfault.core.logger", project_root)
    processes.append(backend)

    # Give the server a moment to start before opening the browser
    time.sleep(2)

    # Open the web app in the default browser
    print(f"Opening {webapp_path}")
    webbrowser.open(webapp_path.as_uri())

    # Wait for the backend to exit (Ctrl+C to stop)
    try:
        backend.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        for p in processes:
            p.terminate()


if __name__ == "__main__":
    main()
