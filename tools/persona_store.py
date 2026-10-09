"""Storage-neutral read interface and a bounded, process-isolated getter.

Workers see only one key/configuration over private pipes, never a bridge socket.
The wire session remains the sole owner of epoch validation and publication.
"""
import json
import os
from pathlib import Path
import selectors
import subprocess
import threading
import time
from typing import Optional, Protocol, Tuple

from tools.persona_errors import InvalidRecord, StoreUnavailable
from tools.persona_protocol import LogicalRecord, ProtocolError, validate_name_key as validate_key

ROOT = Path(__file__).resolve().parents[1]
LOOKUP_TIMEOUT = 1.5
REAP_TIMEOUT = 0.25
MAX_REQUEST_BYTES = 4096
MAX_REPLY_BYTES = 2048
DEFAULT_CAPACITY = 2


class PersonaStore(Protocol):
    def get(self, name_words: Tuple[int, int]) -> Optional[LogicalRecord]:
        """Return a complete record or positive absence; raise on every failure."""
        ...


class IsolatedPersonaStore:
    """Bound total wall time, result size and concurrent driver processes.

    A worker's valid-looking output is accepted only after successful exit within
    the deadline. On error it is killed and reaped. In the exceptional case that
    SIGKILL cannot be reaped promptly, its capacity slot stays occupied until a
    bounded-number daemon reaper confirms exit; it is never silently recycled.
    """
    def __init__(self, command, configuration, *, timeout=LOOKUP_TIMEOUT, capacity=DEFAULT_CAPACITY):
        if not command or timeout <= 0 or type(capacity) is not int or capacity < 1:
            raise ValueError('Invalid worker configuration')
        self.command, self.configuration = tuple(command), dict(configuration)
        self.timeout = timeout
        self._slots = threading.BoundedSemaphore(capacity)
        self._lock = threading.Lock()
        self._processes = set()
        self._closed = False

    @property
    def worker_pids(self):
        with self._lock:
            return frozenset(process.pid for process in self._processes)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        with self._lock:
            self._closed = True
            processes = list(self._processes)
        for process in processes:
            self._kill(process)

    @staticmethod
    def _kill(process):
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def _release(self, process):
        with self._lock:
            self._processes.discard(process)
        self._slots.release()

    def _late_reap(self, process):
        process.wait()
        self._release(process)

    def get(self, name_words):
        key = validate_key(name_words)
        return self.call({'name_words': key}, lambda raw: self._decode_result(key, raw))

    def call(self, request, decode):
        """One bounded worker operation. The caller supplies a typed decoder."""
        if not self._slots.acquire(blocking=False):
            raise StoreUnavailable()
        process = None
        try:
            deadline = time.monotonic() + self.timeout
            with self._lock:
                if self._closed:
                    raise StoreUnavailable()
            payload = json.dumps(dict(request, config=self.configuration)).encode('ascii')
            if len(payload) > MAX_REQUEST_BYTES:
                raise StoreUnavailable()
            process = subprocess.Popen(self.command, cwd=ROOT, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       bufsize=0, close_fds=True)
            with self._lock:
                self._processes.add(process)
                if self._closed:
                    raise StoreUnavailable()
            raw = self._exchange(process, payload, deadline)
            record = decode(raw)
            with self._lock:
                if self._closed or time.monotonic() >= deadline:
                    raise StoreUnavailable()
                return record
        except InvalidRecord:
            raise
        except Exception:
            raise StoreUnavailable() from None
        finally:
            if process is None:
                self._slots.release()
            else:
                self._kill(process)
                for stream in (process.stdin, process.stdout):
                    stream.close()
                try:
                    process.wait(timeout=REAP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    threading.Thread(target=self._late_reap, args=(process,), daemon=True).start()
                else:
                    self._release(process)

    @staticmethod
    def _decode_result(key, raw):
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise StoreUnavailable()
        status = result.get('status')
        if status == 'FOUND' and set(result) == {'status', 'words'}:
            try:
                record = LogicalRecord(result['words'])
                if record.name_words != key:
                    raise InvalidRecord()
            except ProtocolError:
                raise InvalidRecord() from None
            return record
        if set(result) != {'status'}:
            raise StoreUnavailable()
        if status == 'NOT_FOUND':
            return None
        if status == 'INVALID_RECORD':
            raise InvalidRecord()
        raise StoreUnavailable()

    @staticmethod
    def _exchange(process, payload, deadline):
        sent, result = 0, bytearray()
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            eof = False
            while not eof:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StoreUnavailable()
                for key, _ in selector.select(remaining):
                    if key.fileobj is process.stdin:
                        sent += os.write(key.fd, payload[sent:])
                        if sent == len(payload):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        data = os.read(key.fd, MAX_REPLY_BYTES + 1 - len(result))
                        if not data:
                            eof = True
                            break
                        result.extend(data)
                        if len(result) > MAX_REPLY_BYTES:
                            raise StoreUnavailable()
            remaining = deadline - time.monotonic()
            if remaining <= 0 or process.wait(timeout=remaining) != 0 or time.monotonic() >= deadline:
                raise StoreUnavailable()
        return bytes(result)
