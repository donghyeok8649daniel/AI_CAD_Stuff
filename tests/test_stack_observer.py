import gc
import json
import queue
import sys
import threading
import time
import types
import weakref
from pathlib import Path

import pytest

from cadstudio.stack_observer import ObserverCleanupError, ObserverFailure, StackObserver


def wait_for(predicate, timeout=2):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return
        threading.Event().wait(0.005)
    raise AssertionError("bounded condition did not arrive")


def test_real_start_sample_stop_closes_only_own_thread(tmp_path):
    before_threads = {t.ident for t in threading.enumerate()}
    before_fatal_module = sys.modules.get("faulthandler")
    out = tmp_path / "real.jsonl"
    observer = StackObserver(out, interval=0.01).start()
    own_thread = observer._thread
    own_stream = observer._stream
    assert own_thread.daemon
    assert observer.sampled.wait(2)
    result = observer.stop()
    assert result["success"] and result["samples"] >= 1
    assert not own_thread.is_alive() and own_stream.closed
    assert observer._thread is None and observer._stream is None
    assert {t.ident for t in threading.enumerate()} == before_threads
    assert sys.modules.get("faulthandler") is before_fatal_module
    records = [json.loads(line) for line in out.read_bytes().splitlines()]
    assert records and records[0]["threads"][0]["main"]
    assert records[0]["threads"][0]["thread"] == threading.main_thread().ident
    for record in records:
        assert len(record["threads"]) <= 32
        assert record["captured_frames"] <= 64
        for thread in record["threads"]:
            for frame in thread["frames"]:
                assert set(frame) == {"file", "line", "function"}
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        observer.start()


def test_frame_snapshot_does_not_retain_finished_thread_locals(tmp_path):
    refs = queue.Queue()
    leave = threading.Event()

    class Marker:
        pass

    def target():
        marker = Marker()
        refs.put(weakref.ref(marker))
        leave.wait(2)

    target_thread = threading.Thread(target=target, name="owned-marker-thread")
    target_thread.start()
    marker_ref = refs.get(timeout=1)
    observer = StackObserver(tmp_path / "release.jsonl", interval=0.01).start()
    assert observer.sampled.wait(2)
    observer.stop()
    leave.set()
    target_thread.join(2)
    assert not target_thread.is_alive()
    gc.collect()
    assert marker_ref() is None
    assert not any(isinstance(value, types.FrameType)
                   for value in vars(observer).values())
    assert observer._thread is None and observer._stream is None


def test_contended_shared_lock_stop_remains_bounded(tmp_path):
    shared = threading.RLock()
    locked = threading.Event()
    release = threading.Event()

    def holder():
        with shared:
            locked.set()
            release.wait(2)

    holder_thread = threading.Thread(target=holder, name="owned-lock-holder")
    holder_thread.start()
    assert locked.wait(1)
    observer = StackObserver(tmp_path / "locked.jsonl", shared_lock=shared,
                             interval=0.005, lock_timeout=0.02).start()
    wait_for(lambda: observer.lock_misses >= 1)
    begun = time.monotonic()
    result = observer.stop(join_timeout=0.2)
    assert time.monotonic() - begun < 0.4
    assert result["success"] and result["lock_misses"] >= 1
    assert observer._stream is None and observer._thread is None
    release.set()
    holder_thread.join(2)
    assert not holder_thread.is_alive()


def test_join_timeout_retains_stream_then_can_cleanup(tmp_path):
    entered = threading.Event()
    release = threading.Event()

    def slow_provider():
        entered.set()
        release.wait(2)
        return sys._current_frames()

    observer = StackObserver(tmp_path / "timeout.jsonl", interval=0.005,
                             frame_provider=slow_provider).start()
    assert entered.wait(1)
    stream = observer._stream
    thread = observer._thread
    with pytest.raises(ObserverCleanupError, match="stream retained"):
        observer.stop(join_timeout=0.01)
    assert observer._stream is stream and not stream.closed
    assert observer._thread is thread and thread.is_alive()
    assert not observer.status()["success"]
    release.set()
    assert observer.stop(join_timeout=1)["success"]
    assert stream.closed and observer._stream is None


def test_external_closing_prevents_new_write(tmp_path):
    closing = threading.Event()
    observer = StackObserver(tmp_path / "closing.jsonl", closing_event=closing,
                             interval=0.01).start()
    assert observer.sampled.wait(2)
    closing.set()
    wait_for(lambda: not observer._thread.is_alive())
    samples = observer.samples
    observer.stop()
    assert observer.samples == samples
    with pytest.raises(RuntimeError, match="closing"):
        StackObserver(tmp_path / "never.jsonl", closing_event=closing).start()
    assert not (tmp_path / "never.jsonl").exists()


def test_blocked_file_write_releases_report_lock_and_retains_stream(tmp_path):
    entered, release = threading.Event(), threading.Event()
    shared = threading.RLock()
    observer = StackObserver(tmp_path / "blocked-write.jsonl", interval=0.05,
                             shared_lock=shared).start()
    original = observer._stream

    class BlockedWrite:
        @property
        def closed(self):
            return original.closed

        def write(self, payload):
            entered.set()
            release.wait(3)
            return original.write(payload)

        def flush(self):
            original.flush()

        def close(self):
            original.close()

    replacement = BlockedWrite()
    observer._stream = replacement
    try:
        assert entered.wait(2)
        assert shared.acquire(timeout=0.05)
        shared.release()
        with pytest.raises(ObserverCleanupError, match="stream retained"):
            observer.stop(join_timeout=0.01)
        assert observer._stream is replacement and not original.closed
        assert not observer.status()["success"]
    finally:
        release.set()
        assert observer.stop(join_timeout=2)["success"]
        assert original.closed and observer._stream is None


def test_byte_thread_and_total_frame_caps_real_stack(tmp_path):
    ready = queue.Queue()
    leave = threading.Event()
    workers = []

    def deep(depth):
        if depth:
            return deep(depth - 1)
        ready.put(True)
        leave.wait(3)

    try:
        for _ in range(4):
            worker = threading.Thread(target=deep, args=(75,), name="owned-deep-thread")
            workers.append(worker)
            worker.start()
        for _ in workers:
            ready.get(timeout=1)
        out = tmp_path / "capped.jsonl"
        observer = StackObserver(out, interval=0.01, max_threads=2,
                                 max_frames=8, max_bytes=512,
                                 max_total_bytes=512).start()
        assert observer.sampled.wait(2)
        wait_for(lambda: observer.output_capped)
        assert not observer.stop()["success"]
        assert out.stat().st_size <= 512
        for raw in out.read_bytes().splitlines(keepends=True):
            assert len(raw) <= 512
            record = json.loads(raw)
            assert len(record["threads"]) <= 2
            assert record["captured_frames"] <= 8
            assert record["omitted_threads"] >= 4
            assert record["byte_limit_reached"]
            assert record["threads"][0]["main"]
    finally:
        leave.set()
        for worker in workers:
            worker.join(2)
        assert all(not worker.is_alive() for worker in workers)


def test_observer_error_cannot_be_reported_as_success(tmp_path):
    def failed_provider():
        raise LookupError("owned injected collection failure")

    shared = threading.RLock()
    observer = StackObserver(tmp_path / "failure.jsonl", interval=0.005,
                             shared_lock=shared,
                             frame_provider=failed_provider).start()
    wait_for(lambda: observer.status()["error"] is not None)
    with pytest.raises(ObserverFailure, match="LookupError"):
        observer.stop()
    assert observer.status()["cleaned"]
    assert not observer.status()["success"]
    assert observer._stream is None and observer._thread is None
    assert shared.acquire(timeout=0.05)
    shared.release()
    with pytest.raises(ObserverFailure):
        observer.stop()


def test_invalid_bounds_fail_before_file_or_thread_creation(tmp_path):
    for kwargs in ({"max_threads": 33}, {"max_frames": 65},
                   {"max_bytes": 256 * 1024 + 1}, {"max_bytes": 511},
                   {"max_total_bytes": 8 * 1024 * 1024 + 1},
                   {"max_total_bytes": 511},
                   {"lock_timeout": 2}, {"interval": 0}):
        with pytest.raises(ValueError):
            StackObserver(tmp_path / "invalid.jsonl", **kwargs)
    assert not (tmp_path / "invalid.jsonl").exists()


def test_unstarted_cleanup_and_existing_file_cannot_pass(tmp_path):
    out = tmp_path / "not-started.jsonl"
    observer = StackObserver(out)
    with pytest.raises(ObserverCleanupError, match="not started"):
        observer.stop()
    assert not observer.status()["success"]
    out.write_bytes(b"preserved previous diagnostic")
    with pytest.raises(FileExistsError):
        observer.start()
    assert out.read_bytes() == b"preserved previous diagnostic"
    assert not observer.status()["success"]


def test_summary_avoids_source_loader_and_frame_locals(tmp_path, monkeypatch):
    import linecache

    def forbidden_loader(*args, **kwargs):
        raise AssertionError("source loader must not be called")

    monkeypatch.setattr(linecache, "getline", forbidden_loader)
    observer = StackObserver(tmp_path / "source-free.jsonl", interval=0.01).start()
    assert observer.sampled.wait(2)
    assert observer.stop()["success"]


def test_close_during_collection_skips_write(tmp_path):
    closing = threading.Event()
    entered = threading.Event()
    release = threading.Event()

    def held_provider():
        entered.set()
        release.wait(2)
        return sys._current_frames()

    out = tmp_path / "closing-during-sample.jsonl"
    observer = StackObserver(out, closing_event=closing, interval=0.005,
                             frame_provider=held_provider).start()
    assert entered.wait(1)
    closing.set()
    release.set()
    assert observer.stop()["success"]
    assert observer.samples == 0 and out.read_bytes() == b""


def test_source_free_access_and_default_max_thread_count(tmp_path):
    class Code:
        co_filename = "owned-only.py"
        co_name = "owned_function"

    class Location:
        f_code = Code()
        f_lineno = 7
        f_back = None

        @property
        def f_locals(self):
            raise AssertionError("locals must not be inspected")

        @property
        def f_globals(self):
            raise AssertionError("globals must not be inspected")

    main = threading.main_thread().ident
    locations = {main: Location()}
    locations.update({main + n: Location() for n in range(1, 45)})
    observer = StackObserver(tmp_path / "locations.jsonl", interval=0.01,
                             frame_provider=lambda: locations).start()
    assert observer.sampled.wait(2)
    assert observer.stop()["success"]
    for raw in (tmp_path / "locations.jsonl").read_bytes().splitlines():
        record = json.loads(raw)
        assert len(record["threads"]) == 32
        assert record["omitted_threads"] == 13
        assert record["threads"][0]["thread"] == main
        assert record["captured_frames"] == 32
    assert len(locations) == 45  # observer clears its copy, not caller data


def test_multiple_real_samples_have_independent_file_budget(tmp_path):
    out = tmp_path / "independent-budgets.jsonl"
    observer = StackObserver(out, interval=0.01, max_threads=1, max_frames=1,
                             max_bytes=2048, max_total_bytes=8192).start()
    wait_for(lambda: observer.samples >= 5)
    result = observer.stop()
    assert result["success"] and not result["output_capped"]
    assert result["sample_byte_capped"] == 0
    assert 2048 < out.stat().st_size <= 8192
    assert all(len(raw) <= 2048 for raw in out.read_bytes().splitlines(keepends=True))


def test_sample_byte_truncation_is_incomplete_without_file_exhaustion(tmp_path):
    out = tmp_path / "sample-cap.jsonl"
    observer = StackObserver(out, interval=0.01, max_bytes=512).start()
    assert observer.sampled.wait(2)
    result = observer.stop()
    assert result["cleaned"] and not result["success"]
    assert result["sample_byte_capped"] >= 1
    assert not result["output_capped"]
    assert not observer.status()["success"]
    assert out.stat().st_size < 8 * 1024 * 1024
    assert all(len(raw) <= 512 for raw in out.read_bytes().splitlines(keepends=True))
