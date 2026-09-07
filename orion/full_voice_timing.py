"""High-resolution observations in the existing explicit Test Session buffer.

Windows runtime timers use coarse GetTickCount64. These QueryPerformanceCounter
observations never replace them. No I/O, text/PCM retention or lifecycle control.
"""
import time

from orion.realtime_test_evidence import realtime_test_evidence


def observe(boundary, turn=None, *, response_id=None):
    try:
        stamp = time.perf_counter()
        realtime_test_evidence.record(
            "full_voice_timing", event_id=boundary,
            turn_id=str(turn) if turn is not None else None,
            response_id=response_id, perf_counter_seconds=stamp,
        )
    except Exception:
        # A measurement failure must not alter the accepted voice turn.
        pass
