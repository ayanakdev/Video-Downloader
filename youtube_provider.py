"""Build and manage one local PO-token service for this app process."""
import atexit
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from urllib.request import build_opener, ProxyHandler

from filelock import FileLock, Timeout

SOURCE = Path(__file__).resolve().parent / "vendor" / "bgutil"
_lock = threading.Lock()
_process = None
_endpoint = None


class ProviderError(RuntimeError):
    pass


def _stop():
    global _process, _endpoint
    if _process is not None and _process.poll() is None:
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
            _process.wait(timeout=5)
    _process = None
    _endpoint = None


atexit.register(_stop)


def _tail(path, limit=600):
    """Surface why the service died; setup failures are otherwise invisible."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:].strip() or "no output"
    except OSError:
        return "log unavailable"


def _build(node):
    # Include source and dependency lock in the cache key so upgrades rebuild.
    digest = hashlib.sha256(str(node).encode())
    for path in sorted(SOURCE.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(SOURCE).as_posix().encode())
            digest.update(path.read_bytes())
    runtime = Path(tempfile.gettempdir()) / ("getvideo-pot-" + digest.hexdigest()[:16])
    with FileLock(str(runtime) + ".lock", timeout=360):
        if (runtime / ".ready").is_file():
            return runtime
        shutil.copytree(SOURCE, runtime, dirs_exist_ok=True)
        node = Path(node).resolve()
        npm = next((p for root in (node.parent, node.parent.parent)
                    for p in (root / "lib/node_modules/npm/bin/npm-cli.js",
                              root / "node_modules/npm/bin/npm-cli.js") if p.is_file()), None)
        if npm is None:
            raise ProviderError("Node's npm is missing. Reinstall nodejs-wheel and reboot the app.")
        env = {**os.environ, "PATH": str(node.parent) + os.pathsep + os.environ.get("PATH", "")}
        commands = ([str(node), str(npm), "ci", "--no-audit", "--no-fund"],
                    [str(node), str(runtime / "node_modules/typescript/bin/tsc")])
        for command in commands:
            try:
                result = subprocess.run(command, cwd=runtime, env=env,
                                        capture_output=True, text=True, timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ProviderError("YouTube token service setup could not finish. Reboot and retry; check server logs.") from error
            if result.returncode:
                # Full build errors go to server logs, never into user downloads.
                print("YouTube token service build failed:\n" + result.stdout[-4000:] + result.stderr[-4000:])
                raise ProviderError("YouTube token service setup failed. Check server logs for npm/build errors.")
        (runtime / ".ready").write_text("2.0.0", encoding="utf-8")
    return runtime


def ensure_provider(node):
    """Return the loopback endpoint; serialize cold starts across Streamlit sessions."""
    global _process, _endpoint
    if not node or not Path(node).is_file():
        raise ProviderError("YouTube requires Node. Install requirements.txt and reboot the app.")
    with _lock:
        if _process is not None and _process.poll() is None:
            return _endpoint
        try:
            runtime = _build(node)
        except Timeout as error:
            raise ProviderError("YouTube service setup is still busy. Wait a moment and retry.") from error
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        _endpoint = f"http://127.0.0.1:{port}"
        # Token responses remain internal. Bind only loopback, not the public app port.
        log_path = runtime / f"service-{os.getpid()}.log"
        with log_path.open("a", encoding="utf-8") as log:
            _process = subprocess.Popen(
                [str(node), str(runtime / "build/main.js"), "--host", "127.0.0.1", "--port", str(port)],
                cwd=runtime, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        # A tight host can OOM-kill the server between requests, so allow a full
        # bind and first-token window before declaring the provider healthy.
        for _ in range(300):
            if _process.poll() is not None:
                break
            try:
                with build_opener(ProxyHandler({})).open(_endpoint + "/ping", timeout=2) as response:
                    if json.load(response).get("version") == "2.0.0":
                        return _endpoint
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        _stop()
        raise ProviderError(f"YouTube token service did not start. Server log: {_tail(log_path)}")
