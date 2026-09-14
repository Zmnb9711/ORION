"""One explicit four-turn Step 5 semantic gate; no audio, retries or real DCS."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import foundation_fact_gate as gate

# Developer-created fixtures; never supplied as physical user test phrases.
CASES = (
    ('mixed_ru', 'Коротко объясни, почему стекло прозрачно, и сообщи текущий тангаж моего самолёта.',
     'MIXED', ('ownship.pitch',), 'ru-RU'),
    ('followup_ru', 'Каково сейчас значение того же параметра моего борта?',
     'FACT_REQUEST', ('ownship.pitch',), 'ru-RU'),
    ('mixed_en', 'Give a short thought about learning a new craft, and report my present true airspeed.',
     'MIXED', ('ownship.true_airspeed',), 'en-US'),
    ('followup_en', 'Read that same aircraft parameter again now.',
     'FACT_REQUEST', ('ownship.true_airspeed',), 'en-US'),
)


if __name__ == '__main__':
    gate.CASES = CASES
    gate.main()
