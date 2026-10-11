"""Start the local-only industrial workbench and open its browser page."""

import os
import sys
import threading
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server import app


def main() -> None:
    port = int(os.environ.get("MODUBOARD_PORT", "5000"))
    url = f"http://127.0.0.1:{port}/industrial"
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Industrial Workbench: {url}")
    print("Press Ctrl+C to stop. Real device mode is read-only.")
    host = os.environ.get("MODUBOARD_HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
