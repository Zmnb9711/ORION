from __future__ import annotations

import queue

import pytest

from orion.yandex_live_audio_core import PlaybackSlice, ResponsePlaybackQueue


def test_uninterrupted_response_preserves_byte_identity_and_order() -> None:
    playback = ResponsePlaybackQueue()
    epoch = playback.response_created("r1")
    pcm = bytes(range(252)) * 15
    queued, stale = playback.enqueue_delta("r1", pcm)
    written: list[bytes] = []
    for _ in range(queued):
        item = playback.get()
        assert isinstance(item, PlaybackSlice)
        assert item.epoch == epoch
        assert playback.is_current(item)
        written.append(item.pcm)
    assert stale == 0
    assert b"".join(written) == pcm


def test_barge_in_removes_queued_old_audio_and_late_delta_is_stale() -> None:
    playback = ResponsePlaybackQueue()
    playback.response_created("old")
    playback.enqueue_delta("old", b"a" * 3528)
    response_id, removed = playback.invalidate_active()
    queued, stale = playback.enqueue_delta("old", b"b" * 1764)
    assert response_id == "old"
    assert removed == 2
    assert queued == 0
    assert stale == 1
    with pytest.raises(queue.Empty):
        playback.get(timeout=0.01)


def test_current_committed_slice_may_finish_but_no_next_stale_slice() -> None:
    playback = ResponsePlaybackQueue()
    playback.response_created("old")
    playback.enqueue_delta("old", b"a" * 3528)
    committed = playback.get()
    assert isinstance(committed, PlaybackSlice)
    _, removed = playback.invalidate_active()
    assert removed == 1
    assert not playback.is_current(committed)


def test_old_done_cannot_affect_new_response() -> None:
    playback = ResponsePlaybackQueue()
    playback.response_created("old")
    playback.invalidate_active()
    new_epoch = playback.response_created("new")
    playback.response_done("old")
    queued, stale = playback.enqueue_delta("new", b"n" * 1764)
    item = playback.get()
    assert queued == 1 and stale == 0
    assert isinstance(item, PlaybackSlice)
    assert item.response_id == "new" and item.epoch == new_epoch


def test_response_done_before_physical_drain_still_allows_barge_in_removal() -> None:
    playback = ResponsePlaybackQueue()
    playback.response_created("completed-provider-response")
    playback.enqueue_delta("completed-provider-response", b"q" * 3528)
    playback.response_done("completed-provider-response")
    response_id, removed = playback.invalidate_active()
    assert response_id == "completed-provider-response"
    assert removed == 2
    with pytest.raises(queue.Empty):
        playback.get(timeout=0.01)


def test_delta_without_repeated_response_id_uses_created_response_ownership() -> None:
    playback = ResponsePlaybackQueue()
    playback.response_created("created-response")
    queued, stale = playback.enqueue_delta("created-response", b"p" * 1764)
    item = playback.get()
    assert (queued, stale) == (1, 0)
    assert isinstance(item, PlaybackSlice)
    assert item.response_id == "created-response"


def test_repeated_interruption_keeps_new_epoch_healthy() -> None:
    playback = ResponsePlaybackQueue()
    for index in range(3):
        response_id = f"r{index}"
        playback.response_created(response_id)
        playback.enqueue_delta(response_id, b"x" * 1764)
        playback.invalidate_active()
    playback.response_created("healthy")
    queued, stale = playback.enqueue_delta("healthy", b"z" * 1764)
    assert (queued, stale) == (1, 0)
