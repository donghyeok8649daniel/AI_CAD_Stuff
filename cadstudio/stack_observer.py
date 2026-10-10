"""Bounded QA observer. Does not alter Python's fatal handler.

The output contains code locations, never source text, locals, or globals. An
unsuccessful join retains the live thread and stream so the owner cannot mistake
an incomplete shutdown for a successful cleanup.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Mapping


class ObserverFailure(RuntimeError):
    pass


class ObserverCleanupError(RuntimeError):
    pass


class StackObserver:
    def __init__(
        self,
        output: Path,
        *,
        shared_lock=None,
        closing_event: threading.Event | None = None,
        interval: float = 1.0,
        lock_timeout: float = 0.05,
        max_threads: int = 32,
        max_frames: int = 64,
        max_bytes: int = 256 * 1024,
        max_total_bytes: int = 8 * 1024 * 1024,
        frame_provider: Callable[[], Mapping] | None = None,
    ):
        if not 0 < interval <= 3600 or not 0 < lock_timeout <= 1:
            raise ValueError("interval/lock timeout outside observer bounds")
        if not 1 <= max_threads <= 32 or not 1 <= max_frames <= 64:
            raise ValueError("thread/frame limit outside observer bounds")
        if not 512 <= max_bytes <= 256 * 1024:
            raise ValueError("byte limit outside observer bounds")
        if not 512 <= max_total_bytes <= 8 * 1024 * 1024:
            raise ValueError("total byte limit outside observer bounds")
        self.output = Path(output)
        self.interval = interval
        self.lock_timeout = lock_timeout
        self.max_threads = max_threads
        self.max_frames = max_frames
        self.max_bytes = max_bytes
        self.max_total_bytes = max_total_bytes
        self._shared_lock = shared_lock or threading.RLock()
        self._external_closing = closing_event
        self._closing = threading.Event()
        self._stop = threading.Event()
        self.sampled = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._frame_provider = frame_provider or sys._current_frames
        self._stream = None
        self._thread = None
        self._started = False
        self._cleaned = False
        self._error = None
        self.samples = 0
        self.bytes_written = 0
        self.output_capped = False
        self.sample_byte_capped = 0
        self.lock_misses = 0
        self.observer_thread_id = None

    def _is_closing(self):
        return self._closing.is_set() or (
            self._external_closing is not None
            and self._external_closing.is_set()
        )

    def start(self):
        with self._lifecycle_lock:
            if self._started:
                raise RuntimeError("an observer cannot be restarted")
            if self._is_closing():
                raise RuntimeError("closing observer cannot start")
            self._stream = self.output.open("xb")
            self._thread = threading.Thread(
                target=self._run,
                name="owned-safe-stack-observer",
                daemon=True,
            )
            self._started = True
            try:
                self._thread.start()
            except BaseException:
                self._stream.close()
                self._stream = None
                self._thread = None
                self._cleaned = True
                self._error = "thread_start_failed"
                raise
        return self

    @staticmethod
    def _short(value, bound):
        value = str(value)
        return value if len(value) <= bound else value[: bound - 3] + "..."

    def _collect_sample(self):
        # The snapshot dictionary owns strong frame references until finally.
        # Do not retain it or individual frames in the observer instance.
        snapshot = None
        frame = None
        records = []
        main_id = threading.main_thread().ident
        captured = 0
        frame_limit_reached = False
        try:
            snapshot = dict(self._frame_provider())
            ids = sorted(snapshot)
            if main_id in snapshot:
                ids.remove(main_id)
                ids.insert(0, main_id)
            selected = ids[: self.max_threads]
            for thread_id in selected:
                frame = snapshot[thread_id]
                locations = []
                while frame is not None and captured < self.max_frames:
                    code = frame.f_code
                    locations.append(
                        {
                            "file": self._short(code.co_filename, 2048),
                            "line": int(frame.f_lineno),
                            "function": self._short(code.co_name, 256),
                        }
                    )
                    captured += 1
                    frame = frame.f_back
                if frame is not None:
                    frame_limit_reached = True
                records.append(
                    {"thread": thread_id, "main": thread_id == main_id,
                     "frames": locations}
                )
                frame = None
            record = {
                "kind": "stack_sample",
                "monotonic": time.monotonic(),
                "threads": records,
                "omitted_threads": len(ids) - len(selected),
                "captured_frames": captured,
                "frame_limit_reached": frame_limit_reached,
                "byte_limit_reached": False,
                "limits": {"threads": self.max_threads,
                           "frames_total": self.max_frames,
                           "bytes_per_sample": self.max_bytes,
                           "bytes_total": self.max_total_bytes},
            }
            while True:
                payload = (json.dumps(record, ensure_ascii=True,
                                      separators=(",", ":")) + "\n").encode("ascii")
                if len(payload) <= self.max_bytes:
                    return payload, record["byte_limit_reached"]
                record["byte_limit_reached"] = True
                # Preserve main-first and most recent frame order; discard
                # only trailing locations and then empty trailing threads.
                if records and records[-1]["frames"]:
                    records[-1]["frames"].pop()
                    record["captured_frames"] -= 1
                elif records:
                    records.pop()
                    record["omitted_threads"] += 1
                else:
                    raise ObserverFailure("bounded metadata exceeds byte cap")
        finally:
            frame = None
            if snapshot is not None:
                snapshot.clear()
            snapshot = None

    def _run(self):
        self.observer_thread_id = threading.get_ident()
        try:
            while not self._stop.wait(self.interval):
                if self._is_closing():
                    break
                acquired = self._shared_lock.acquire(timeout=self.lock_timeout)
                if not acquired:
                    self.lock_misses += 1
                    continue
                try:
                    if self._is_closing():
                        break
                finally:
                    self._shared_lock.release()
                # This stream has one writer. Never hold the stage/report lock
                # during collection or filesystem I/O: a blocked write must not
                # prevent the owner from recording a failed bounded join.
                payload, sample_capped = self._collect_sample()
                if self._is_closing():
                    break
                if self.bytes_written + len(payload) > self.max_total_bytes:
                    self.output_capped = True
                    self._stop.set()
                    break
                written = self._stream.write(payload)
                if written != len(payload):
                    raise ObserverFailure("incomplete diagnostic write")
                self.bytes_written += written
                self._stream.flush()
                self.samples += 1
                self.sample_byte_capped += int(sample_capped)
                self.sampled.set()
        except BaseException as exc:
            # Store a bounded error type, never a traceback with frame refs.
            self._error = type(exc).__name__
            self._stop.set()

    def stop(self, *, join_timeout: float = 1.0):
        if not 0 <= join_timeout <= 10:
            raise ValueError("join timeout outside observer bounds")
        with self._lifecycle_lock:
            if not self._started:
                raise ObserverCleanupError("observer has not started")
            self._closing.set()
            self._stop.set()
            thread = self._thread
        # No lock is held while joining. In particular, a contended stage
        # writer lock cannot make stop wait indefinitely.
        if thread is threading.current_thread():
            raise ObserverCleanupError("observer cannot join itself")
        if thread is not None:
            thread.join(join_timeout)
            if thread.is_alive():
                raise ObserverCleanupError("observer still alive; stream retained")
        with self._lifecycle_lock:
            if self._stream is not None:
                try:
                    self._stream.close()
                except BaseException as exc:
                    self._error = type(exc).__name__
                    raise ObserverCleanupError("stream close failed; stream retained") from None
                self._stream = None
            self._thread = None
            self._cleaned = True
        if self._error is not None:
            raise ObserverFailure("observer failed: " + self._error)
        return {"success": not self.output_capped and not self.sample_byte_capped,
                "cleaned": True,
                "samples": self.samples, "bytes_written": self.bytes_written,
                "output_capped": self.output_capped,
                "sample_byte_capped": self.sample_byte_capped,
                "lock_misses": self.lock_misses,
                "observer_thread_id": self.observer_thread_id}

    def status(self):
        thread = self._thread
        return {"started": self._started, "cleaned": self._cleaned,
                "alive": bool(thread and thread.is_alive()),
                "stream_retained": self._stream is not None,
                "samples": self.samples, "lock_misses": self.lock_misses,
                "bytes_written": self.bytes_written,
                "output_capped": self.output_capped,
                "sample_byte_capped": self.sample_byte_capped,
                "error": self._error,
                "success": self._started and self._cleaned
                and self._error is None and not self.output_capped
                and not self.sample_byte_capped}
