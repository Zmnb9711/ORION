"""Provider-free cleanup tests with real transport loops and controlled blockers."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import threading
import time
from typing import Any
from types import SimpleNamespace

import pytest

from orion.planner import PlannerCancellationToken
from orion.planner_contracts import PlannerFinalResponseEvent, PlannerFailedEvent
import orion.yandex_qwen_planner as q
import test_yandex_qwen_planner as fixtures


class Session:
    def __init__(self):
        self.closed = False
        self.deletes = []
        self.closes = 0
        self.delete_entered = threading.Event()
        self.close_entered = threading.Event()
        self.delete_release = asyncio.Event()
        self.close_release = asyncio.Event()
        self.block_delete = self.block_close = False
        self.fail_delete = self.fail_close = False
        self.status = 200

    def delete(self, url):
        self.deletes.append(url.rsplit("/", 1)[-1])
        session = self

        class Response:
            status = session.status

            async def __aenter__(self):
                session.delete_entered.set()
                if session.block_delete:
                    await session.delete_release.wait()
                if session.fail_delete:
                    raise RuntimeError("private provider body")
                return self

            async def __aexit__(self, *args):
                pass

        return Response()

    async def close(self):
        self.closes += 1
        self.close_entered.set()
        if self.block_close:
            await self.close_release.wait()
        if self.fail_close:
            raise RuntimeError("private session details")
        self.closed = True


def make():
    transport: Any = q.AiohttpYandexResponsesTransport(fixtures.config())
    session = Session()
    transport._session = session
    run = q.YandexQwenPlannerRun(request=fixtures.provider_request(), config=fixtures.config(),
        transport=transport, diagnostics=q.YandexPlannerDiagnostics())
    return transport, session, run


def rescue(transport, session, releases=()):
    """Test-only release of failed ownership, never part of the production fix."""
    for release in releases:
        release.set()
    if transport._loop.is_closed():
        return
    if transport._thread.is_alive():
        transport._loop.call_soon_threadsafe(transport._loop.stop)
        transport._thread.join(2)
    assert not transport._thread.is_alive()
    # Flush queued submission/cancellation handles before creating a harness
    # task; a timed-out shutdown coroutine must never cancel the harness itself.
    transport._loop.call_soon(transport._loop.stop)
    transport._loop.run_forever()
    for task in asyncio.all_tasks(transport._loop):
        task.cancel()

    async def drain():
        session.block_close = session.fail_close = False
        session.delete_release.set()
        session.close_release.set()
        tasks = {t for t in asyncio.all_tasks() if t is not asyncio.current_task()}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await session.close()

    transport._loop.run_until_complete(drain())
    transport._loop.close()


def closed(transport, session, run):
    assert transport._closed and run._closed and session.closed
    assert not transport._thread.is_alive()
    assert not transport._loop.is_running() and transport._loop.is_closed()


def test_normal_final_repeated_runs_no_accumulation():
    before = set(threading.enumerate())
    for _ in range(5):
        transport, session, run = make()

        async def response(payload):
            return fixtures.response("response-one", fixtures.message(fixtures.final_json()))

        transport._create = response
        event = run.next_event(deadline=datetime.now(UTC) + timedelta(seconds=2),
                               cancellation=PlannerCancellationToken())
        assert isinstance(event, PlannerFinalResponseEvent)
        closed(transport, session, run)
        run.cancel()
        run._cleanup()
        assert transport.close().already_closed
        transport.delete("response-one")
        assert session.deletes == ["response-one"] and session.closes == 1
    assert set(threading.enumerate()) == before


@pytest.mark.parametrize("count", [0, 1, 8])
@pytest.mark.parametrize("mode", ["normal", "slow", "failure", "http_failure"])
def test_delete_shared_budget_and_hygiene(count, mode, record_property):
    transport, session, run = make()
    session.block_delete = mode == "slow"
    session.fail_delete = mode == "failure"
    session.status = 503 if mode == "http_failure" else 200
    run._response_ids = [f"response-{n}" for n in range(count)]
    try:
        began = time.monotonic()
        run.cancel()
        elapsed = time.monotonic() - began
        record_property("cleanup_seconds", elapsed)
        record_property("response_count", count)
        assert elapsed < q._CLEANUP_BUDGET_SECONDS + .15
        closed(transport, session, run)
        if mode == "slow" and count:
            assert session.deletes == ["response-0"]
        else:
            assert len(session.deletes) == count
        expected = mode != "normal" and count > 0
        assert (q.CleanupIssue.DELETE_INCOMPLETE in transport._cleanup_result.issues) == expected
        deadline = transport._cleanup_deadline
        run.cancel()
        assert transport._cleanup_deadline == deadline
    finally:
        rescue(transport, session)


@pytest.mark.parametrize("phase", ["delete", "close"])
def test_slow_phase_released_inside_remaining_budget(phase):
    transport, session, run = make()
    session.block_delete = phase == "delete"
    session.block_close = phase == "close"
    run._response_ids = ["response-one"]
    errors = []

    def clean():
        try:
            run.cancel()
        except BaseException as exc:
            errors.append(exc)

    owner = threading.Thread(target=clean)
    try:
        owner.start()
        entered = session.delete_entered if phase == "delete" else session.close_entered
        release = session.delete_release if phase == "delete" else session.close_release
        assert entered.wait(2)
        deadline = transport._cleanup_deadline
        transport._loop.call_soon_threadsafe(release.set)
        owner.join(2)
        assert not errors and not owner.is_alive()
        assert deadline == transport._cleanup_deadline
        closed(transport, session, run)
    finally:
        owner.join(2)
        rescue(transport, session)


@pytest.mark.parametrize("mode", ["hang", "error"])
def test_session_failure_normalized_bounded_and_idempotent(mode, record_property):
    transport, session, run = make()
    session.block_close = mode == "hang"
    session.fail_close = mode == "error"
    try:
        began = time.monotonic()
        with pytest.raises(q.YandexPlannerCleanupError) as failure:
            run.cancel()
        elapsed = time.monotonic() - began
        record_property("cleanup_seconds", elapsed)
        assert elapsed < q._CLEANUP_BUDGET_SECONDS + .15
        assert q.CleanupIssue.SESSION_CLOSE_FAILED in failure.value.result.issues
        assert "private" not in str(failure.value)
        assert not run._closed and not transport._closed
        assert not session.closed
        before = (session.closes, list(session.deletes), transport._cleanup_deadline)
        for cleanup in (run.cancel, run._cleanup, transport.close):
            with pytest.raises(q.YandexPlannerCleanupError):
                cleanup()
        assert before == (session.closes, session.deletes, transport._cleanup_deadline)
    finally:
        rescue(transport, session)


@pytest.mark.parametrize("mode", ["timeout", "cancel", "late", "delayed_cancel"])
def test_provider_wait_cancel_timeout_and_late_result(mode):
    transport, session, run = make()
    entered, cancelled = threading.Event(), threading.Event()
    release = asyncio.Event()
    token = PlannerCancellationToken()
    outcomes, errors = [], []

    async def response(payload):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            if mode == "delayed_cancel":
                await release.wait()
            elif mode != "late":
                raise
        return fixtures.response("late", fixtures.message(fixtures.final_json()))

    transport._create = response

    def worker():
        try:
            outcomes.append(run.next_event(deadline=datetime.now(UTC) + timedelta(
                seconds=.05 if mode == "timeout" else 2), cancellation=token))
        except BaseException as exc:
            errors.append(exc)

    owner = threading.Thread(target=worker)
    try:
        owner.start()
        assert entered.wait(2)
        if mode != "timeout":
            token.cancel()
        assert cancelled.wait(2)
        if mode == "delayed_cancel":
            transport._loop.call_soon_threadsafe(release.set)
        owner.join(2)
        assert not owner.is_alive() and not errors
        assert len(outcomes) == 1 and isinstance(outcomes[0], PlannerFailedEvent)
        closed(transport, session, run)
    finally:
        token.cancel()
        owner.join(2)
        rescue(transport, session)


def test_noncooperative_pending_task_has_truthful_drain_failure():
    transport, session, run = make()
    entered, release = threading.Event(), threading.Event()
    pulse = asyncio.Event()

    async def stubborn():
        entered.set()
        while not release.is_set():
            try:
                await pulse.wait()
            except asyncio.CancelledError:
                pass

    asyncio.run_coroutine_threadsafe(stubborn(), transport._loop)
    try:
        assert entered.wait(2)
        began = time.monotonic()
        with pytest.raises(q.YandexPlannerCleanupError) as error:
            run.cancel()
        assert time.monotonic() - began < q._CLEANUP_BUDGET_SECONDS + .15
        assert q.CleanupIssue.DRAIN_FAILED in error.value.result.issues
        assert not transport._closed and not run._closed
        assert not transport._loop.is_closed()
        assert not transport._thread.is_alive()
    finally:
        rescue(transport, session, (release,))


@pytest.mark.parametrize("response_count", [1, 8])
def test_thread_alive_deadline_never_closes_loop(monkeypatch, record_property, response_count):
    transport, session, run = make()
    run._response_ids = [f"response-{n}" for n in range(response_count)]
    entered, release = threading.Event(), threading.Event()
    close_calls = []
    original_close = transport._loop.close

    def blocked():
        entered.set()
        release.wait()

    def checked_close():
        close_calls.append(True)
        assert not transport._thread.is_alive() and not transport._loop.is_running()
        original_close()

    monkeypatch.setattr(transport._loop, "close", checked_close)
    transport._loop.call_soon_threadsafe(blocked)
    try:
        assert entered.wait(2)
        began = time.monotonic()
        with pytest.raises(q.YandexPlannerCleanupError) as error:
            run.cancel()
        elapsed = time.monotonic() - began
        record_property("noncooperative_cleanup_seconds", elapsed)
        record_property("response_count", response_count)
        assert elapsed < q._CLEANUP_BUDGET_SECONDS + .15
        assert q.CleanupIssue.THREAD_ALIVE in error.value.result.issues
        assert q.CleanupIssue.DEADLINE in error.value.result.issues
        assert transport._thread.is_alive() and not close_calls
        assert not transport._closed and not run._closed
    finally:
        rescue(transport, session, (release,))


def test_raw_close_error_is_normalized_and_close_after_delete_error():
    class Broken(fixtures.FakeTransport):
        def delete(self, response_id):
            raise RuntimeError("private delete")

        def close(self):
            self.closed = True
            raise RuntimeError("private close")

    fake = Broken([])
    run = q.YandexQwenPlannerRun(request=fixtures.provider_request(), config=fixtures.config(),
        transport=fake, diagnostics=q.YandexPlannerDiagnostics())
    run._response_ids = ["response-one"]
    with pytest.raises(q.YandexPlannerCleanupError) as failure:
        run.cancel()
    assert fake.closed and not run._closed
    assert "private" not in str(failure.value)


def test_to_thread_cancellation_does_not_terminate_blocking_work():
    entered, release, done = threading.Event(), threading.Event(), threading.Event()

    def work():
        entered.set()
        release.wait(2)
        done.set()

    async def exercise():
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not done.is_set()
        finally:
            release.set()
            assert await asyncio.to_thread(done.wait, 2)

    asyncio.run(exercise())


def test_concurrent_cancel_does_not_create_second_cleanup_owner():
    transport, session, run = make()
    session.block_close = True
    errors = []

    def clean():
        try:
            run.cancel()
        except BaseException as exc:
            errors.append(exc)

    owner = threading.Thread(target=clean)
    try:
        owner.start()
        assert session.close_entered.wait(2)
        with pytest.raises(q.YandexPlannerCleanupError) as error:
            run.cancel()
        assert error.value.result.issues == (q.CleanupIssue.IN_PROGRESS,)
        transport._loop.call_soon_threadsafe(session.close_release.set)
        owner.join(2)
        assert not errors and not owner.is_alive()
        closed(transport, session, run)
        assert session.closes == 1
    finally:
        owner.join(2)
        rescue(transport, session)


def test_success_loop_close_only_after_join_and_drain(monkeypatch):
    transport, session, run = make()
    original_close = transport._loop.close
    observed = []

    def checked_close():
        assert not transport._thread.is_alive()
        assert not transport._loop.is_running()
        assert not asyncio.all_tasks(transport._loop)
        assert session.closed
        observed.append(True)
        original_close()

    monkeypatch.setattr(transport._loop, "close", checked_close)
    run.cancel()
    run.cancel()
    assert observed == [True]
    closed(transport, session, run)


def test_delayed_thread_released_inside_shared_deadline(monkeypatch):
    transport, session, run = make()
    entered, release, cleanup_started = threading.Event(), threading.Event(), threading.Event()
    begin = transport._begin_cleanup
    errors = []

    def blocked():
        entered.set()
        release.wait()

    def observed_begin():
        deadline = begin()
        cleanup_started.set()
        return deadline

    def clean():
        try:
            run.cancel()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(transport, "_begin_cleanup", observed_begin)
    transport._loop.call_soon_threadsafe(blocked)
    owner = threading.Thread(target=clean)
    try:
        assert entered.wait(2)
        owner.start()
        assert cleanup_started.wait(2)
        release.set()
        owner.join(2)
        assert not errors and not owner.is_alive()
        closed(transport, session, run)
    finally:
        release.set()
        owner.join(2)
        rescue(transport, session)


def test_concurrent_deadline_initialization_cannot_reset_budget(monkeypatch):
    transport, session, run = make()
    entered, release = threading.Event(), threading.Event()
    errors = []

    def clock():
        if threading.current_thread().name == "budget-initializer" and not entered.is_set():
            entered.set()
            assert release.wait(2)
        return time.monotonic()

    def first():
        try:
            run.cancel()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(q, "time", SimpleNamespace(monotonic=clock))
    owner = threading.Thread(target=first, name="budget-initializer")
    try:
        owner.start()
        assert entered.wait(2)
        with pytest.raises(q.YandexPlannerCleanupError) as error:
            transport.close()
        assert error.value.result.issues == (q.CleanupIssue.IN_PROGRESS,)
        release.set()
        owner.join(2)
        assert not errors and not owner.is_alive()
        deadline = transport._cleanup_deadline
        assert transport.close().already_closed
        assert transport._cleanup_deadline == deadline
        closed(transport, session, run)
    finally:
        release.set()
        owner.join(2)
        rescue(transport, session)
