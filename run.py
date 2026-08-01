"""
Single entry point: starts the background scheduler and the FastAPI/uvicorn
server (which also serves the static HTML/CSS/JS frontend) together, and
shuts both down cleanly on Ctrl+C.

Usage: python run.py
"""
import subprocess
import sys
import signal
import time
import webbrowser
import threading


def _open_browser_delayed():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:8000")


def main():
    scheduler_proc = subprocess.Popen([sys.executable, "scheduler.py"])
    print(f"Scheduler started (pid {scheduler_proc.pid}).")

    server_proc = subprocess.Popen([sys.executable, "server.py"])
    print(f"Server started (pid {server_proc.pid}) at http://127.0.0.1:8000")

    threading.Thread(target=_open_browser_delayed, daemon=True).start()

    def shutdown(signum=None, frame=None):
        print("\nShutting down...")
        for p in (server_proc, scheduler_proc):
            if p.poll() is None:
                p.terminate()
        time.sleep(1)
        for p in (server_proc, scheduler_proc):
            if p.poll() is None:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server_proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()
