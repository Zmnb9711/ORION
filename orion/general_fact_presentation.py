"""Deterministic OUTPUT morphology; no user-language recognition."""
from decimal import Decimal, ROUND_HALF_UP
import math


def unit_word(number: int, forms: tuple[str, str, str]) -> str:
    value = abs(number)
    if 11 <= value % 100 <= 14:
        return forms[2]
    return forms[0] if value % 10 == 1 else forms[1] if 2 <= value % 10 <= 4 else forms[2]


def spoken_coordinates(latitude: float, longitude: float, language: str = "ru-RU") -> str:
    """DDM .01 minute: <=9.26m rounding/axis, <=13.1m planar at equator.

    Whole-minute rounding can lose 926m/axis. Preserve the existing .01-minute
    precision; only the speech representation changes, never stored facts.
    """
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("coordinate_range")
    def axis(value, positive, negative):
        minutes = (Decimal(str(abs(value))) * 60).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        degrees = int(minutes // 60)
        remainder = minutes - degrees*60
        whole = int(remainder)
        hundredths = int((remainder-whole)*100)
        if language.startswith("en"):
            number = f"{whole} point {hundredths:02d}" if hundredths else str(whole)
            return f"{degrees} degrees {number} minutes {negative if value < 0 else positive}"
        if hundredths:
            minute_text = f"{whole} {unit_word(whole, ('целая', 'целых', 'целых'))} {hundredths} {unit_word(hundredths, ('сотая', 'сотых', 'сотых'))} минуты"
        else:
            minute_text = f"{whole} {unit_word(whole, ('минута', 'минуты', 'минут'))}"
        return f"{degrees} {unit_word(degrees, ('градус', 'градуса', 'градусов'))} {minute_text} {negative if value < 0 else positive}"
    if language.startswith("en"):
        return axis(latitude, "north", "south") + ", " + axis(longitude, "east", "west")
    return axis(latitude, "северной широты", "южной широты") + ", " + axis(longitude, "восточной долготы", "западной долготы")


LABELS = {"altitude": "Геометрическая высота над уровнем моря", "pitch": "Угол тангажа",
          "bank": "Угол крена", "yaw": "Угол рыскания по ADI", "heading": "Текущий курс",
          "position": "Координаты", "identity": "Тип самолёта",
          "agl": "Геометрическая высота над поверхностью", "tas": "Истинная воздушная скорость",
          "vertical_speed": "Вертикальная скорость"}

EN_LABELS = {"altitude": "Geometric altitude above sea level", "pitch": "Pitch angle",
             "bank": "Bank angle", "yaw": "ADI yaw angle", "heading": "Current heading",
             "position": "Coordinates", "identity": "Aircraft type", "agl": "Geometric height above ground",
             "tas": "True airspeed", "vertical_speed": "Vertical speed"}


def scalar_text(value: float, presentation: str, language: str = "ru-RU") -> str:
    if not math.isfinite(value):
        raise ValueError("nonfinite_fact")
    if presentation == "heading":
        # Preserve the previously proven value/precision, no reference-frame rewrite.
        return ("Current heading " if language.startswith("en") else "Текущий курс ") + format(Decimal(str(value)), "f") + (" degrees." if language.startswith("en") else " градусов.")
    altitude = presentation in {"altitude", "agl"}
    rounded = Decimal(str(value)).quantize(Decimal("1" if altitude else ".1"), rounding=ROUND_HALF_UP)
    rounded = abs(rounded) if rounded == 0 else rounded  # no negative spoken zero
    number = format(rounded, "f")
    if language.startswith("en"):
        unit = "metres" if altitude else "metres per second" if presentation in {"tas", "vertical_speed"} else "degrees"
        if rounded < 0:
            number = "minus " + format(abs(rounded), "f")
        return f"{EN_LABELS[presentation]} {number} {unit}."
    if presentation in {"tas", "vertical_speed"}:
        if rounded < 0:
            number = "минус " + format(abs(rounded), "f")
        return f"{LABELS[presentation]} {number} метра в секунду."
    forms = ("метр", "метра", "метров") if altitude else ("градус", "градуса", "градусов")
    word = unit_word(int(rounded), forms) if rounded == int(rounded) else forms[1]
    return f"{LABELS[presentation]} {number} {word}."
