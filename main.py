import subprocess
import threading
import webbrowser
import time
import sys
import os


def run_fastapi():
    import uvicorn
    uvicorn.run(
        "api.app:app",
        host="127.0.0.1",
        port=8001,
        log_config=None,   # disable uvicorn logging — fixes NoneType isatty error
    )


def start_ollama():
    try:
        import requests
        requests.get("http://localhost:11434/api/tags", timeout=2)
    except Exception:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(4)


def open_browser():
    time.sleep(5)
    webbrowser.open("http://127.0.0.1:8001")


if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))

    threading.Thread(target=start_ollama, daemon=True).start()
    threading.Thread(target=open_browser, daemon=True).start()
    run_fastapi()