"""Four live follow-ups, offline Core-accepted history; no retries/audio/DCS.

Two different fact pairs, FACT/MIXED predecessors, RU/EN. Developer inputs only.
The model must choose the referent; the harness does not repair its selection.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import foundation_fact_gate as gate


def fact(capability):
    return {'kind':'FACT_REQUEST', 'capabilities':[capability]}


CASES = (
    ('fact_ru', 'Обнови последнее запрошенное измерение.', 'FACT_REQUEST', ('ownship.altitude_msl',), 'ru-RU'),
    ('mixed_ru', 'Хочу узнать, как изменился последний обсуждённый параметр — дай его текущее значение.',
     'FACT_REQUEST', ('ownship.vertical_speed',), 'ru-RU'),
    ('fact_en', 'Refresh the measurement we discussed most recently.', 'FACT_REQUEST', ('ownship.altitude_msl',), 'en-US'),
    ('mixed_en', 'Give me an updated reading for the last quantity we talked about.',
     'FACT_REQUEST', ('ownship.vertical_speed',), 'en-US'),
)
PRECEDING = {
    'fact_ru': (('Сообщи крен.', fact('ownship.bank')), ('Сообщи высоту над уровнем моря.', fact('ownship.altitude_msl'))),
    'fact_en': (('Report bank angle.', fact('ownship.bank')), ('Report altitude above sea level.', fact('ownship.altitude_msl'))),
    'mixed_ru': (('Кратко обсуди музыку и сообщи курс.', {'kind':'MIXED',
        'dialogue':{'kind':'DIALOGUE','text':'Музыка может передавать настроение.'}, 'facts':fact('ownship.heading')}),
        ('Теперь сообщи вертикальную скорость.', fact('ownship.vertical_speed'))),
    'mixed_en': (('Briefly discuss music and report heading.', {'kind':'MIXED',
        'dialogue':{'kind':'DIALOGUE','text':'Music can convey a mood.'}, 'facts':fact('ownship.heading')}),
        ('Now report vertical speed.', fact('ownship.vertical_speed'))),
}


if __name__ == '__main__':
    gate.CASES, gate.PRECEDING = CASES, PRECEDING
    gate.WIRE_TIMELINE = True
    gate.main()
