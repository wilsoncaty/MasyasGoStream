"""One process handle per Python server, preserved across Streamlit reruns/browsers."""

import threading
from collections import deque


class StreamRuntime:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.starting = False
        self.cancel_requested = False
        self.logs = deque(maxlen=100)

    def is_running(self):
        with self.lock:
            return self.starting or (self.process is not None and self.process.poll() is None)

    def append_log(self, message):
        with self.lock:
            self.logs.append(str(message))

    def log_snapshot(self):
        with self.lock:
            return list(self.logs)

    def launch(self, target, args):
        with self.lock:
            if self.is_running():
                return False
            self.starting = True
            self.cancel_requested = False
            self.logs.clear()

        def run():
            try:
                target(*args)
            finally:
                with self.lock:
                    self.starting = False
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            with self.lock:
                self.starting = False
            raise
        return True


runtime = StreamRuntime()
