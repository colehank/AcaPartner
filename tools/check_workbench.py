"""Exercise graph navigation and manuscript persistence against a disposable local service."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_partner.app import App  # noqa: E402
from research_partner.http.server import serve  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="acapartner-browser-") as directory:
        app = App(Path(directory) / "workspace", {"workdesk_w1a": True})
        with serve(app, "127.0.0.1", 0) as server:
            worker = Thread(target=server.serve_forever)
            worker.start()
            try:
                url = f"http://127.0.0.1:{server.server_port}"
                return subprocess.run(
                    [
                        "npm",
                        "test",
                        "--",
                        "research-progress.spec.ts",
                        "native-documents.spec.ts",
                        "--grep",
                        "home hides the retained research graph|Deliverables show retained LaTeX",
                    ],
                    cwd=ROOT / "frontend/workdesk",
                    env={
                        **os.environ,
                        "PROGRESS_TEST_URL": url,
                        "NATIVE_DOCUMENTS_TEST_URL": url,
                    },
                    check=False,
                ).returncode
            finally:
                server.shutdown()
                worker.join()


if __name__ == "__main__":
    raise SystemExit(main())
