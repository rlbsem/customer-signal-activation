"""Real loopback HTTP, shared by demo and integration tests."""

import socket
import threading
import time
from contextlib import contextmanager

import httpx
import uvicorn


@contextmanager
def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", log_level="error"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(url + "/health", timeout=0.2, trust_env=False).is_success:
                    break
            except httpx.TransportError:
                pass
            time.sleep(0.02)
        else:
            raise RuntimeError("local server did not start")
        yield url
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
