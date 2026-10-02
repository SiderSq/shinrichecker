"""Bounded TTL caches and atomic file writes (no executable serialization)."""

from __future__ import annotations
import os
import tempfile
import threading
import time
from collections import OrderedDict
from functools import wraps


class TTLCache:
    def __init__(self, ttl=300, maxsize=8192):
        self.ttl, self.maxsize = ttl, maxsize
        self._values = OrderedDict()
        self._lock = threading.RLock()

    def get(self, key, default=None):
        with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return default
            expiry, value = entry
            if expiry <= time.monotonic():
                del self._values[key]
                return default
            self._values.move_to_end(key)
            return value

    def __contains__(self, key):
        sentinel = object()
        return self.get(key, sentinel) is not sentinel

    def __getitem__(self, key):
        sentinel = object()
        value = self.get(key, sentinel)
        if value is sentinel:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value):
        with self._lock:
            self._values[key] = (time.monotonic() + self.ttl, value)
            self._values.move_to_end(key)
            while len(self._values) > self.maxsize:
                self._values.popitem(last=False)

    def add(self, key):
        self[key] = True

    def clear(self):
        with self._lock:
            self._values.clear()


def synchronized(lock_name):
    def decorate(fn):
        @wraps(fn)
        def run(self, *args, **kwargs):
            with getattr(self, lock_name):
                return fn(self, *args, **kwargs)

        return run

    return decorate


def atomic_write(path, data):
    path = os.path.abspath(path)
    fd, temporary = tempfile.mkstemp(prefix=".shinri-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
