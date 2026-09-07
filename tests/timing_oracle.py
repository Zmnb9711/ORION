"""Exact authorized observation surface, not a waiver for other source changes."""
OBSERVATIONS = {
    "full_voice_capture.py": ['                observe("T0", self.owner)\n'],
    "full_voice_stt.py": ['            observe("T1", self.owner)\n',
                         '        observe("T2", self.owner)\n'],
    "full_voice_core.py": ['        observe("T3", identity)\n',
                          '        observe("T4", identity)\n'],
    "protected_streaming_presentation.py": [
        '            self.streaming_tts.observation_turn_id = context.turn_id\n',
        '            observe("T5", context.turn_id)\n',
        '                    if "tts_first_pcm" not in self.marks:\n'
        '                        observe("T7", context.turn_id)\n',
    ],
    "protected_streaming_tts.py": ['        self.observation_turn_id = None\n',
                                   '            observe("T6", self.observation_turn_id)\n'],
    "full_voice_srs.py": ['        observe("T8", response_id=tx_id)\n',
                         '                    observe("T9", response_id=tx_id)\n',
                         '            observe("T10", response_id=tx_id)\n'],
    "realtime_test_evidence.py": ['    "perf_counter_seconds",\n'],
}


def without_timing(name, actual):
    lines = list(OBSERVATIONS.get(name, ()))
    if name in OBSERVATIONS and name != "realtime_test_evidence.py":
        lines += ["from orion.full_voice_timing import observe\n"]
    for line in lines:
        assert actual.count(line) == 1, (name, line)
        actual = actual.replace(line, "")
    return actual
