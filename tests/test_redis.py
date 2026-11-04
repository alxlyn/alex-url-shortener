import socket
import threading
import time

from limits.storage import storage_from_string

import app as app_module


def test_a_hung_redis_gives_up_quickly():
    # A server that accepts connections and never answers, like a stuck Redis.
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    storage = storage_from_string(f"redis://127.0.0.1:{port}", **app_module.REDIS_OPTIONS)
    errors = []

    def hit():
        try:
            storage.incr("key", 60)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=hit, daemon=True)
    started = time.monotonic()
    worker.start()
    worker.join(timeout=3)
    server.close()
    assert not worker.is_alive(), "the call to Redis hung"
    assert errors and time.monotonic() - started < 2
