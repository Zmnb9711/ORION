"""Code-seeded immutable catalog for the bounded Pilot phraseology experiment."""

from __future__ import annotations

from orion.communication_contracts import (
    CommunicationDomain,
    CommunicationProfileId,
    ProtectedValueKind,
)
from orion.pilot_phraseology import (
    CATALOG_VERSION,
    PilotFormatterId,
    PilotLanguageRealization,
    PilotPhraseologyCatalog,
    PilotPhraseologyEntry,
    PilotSelector,
    PilotSlotDefinition,
)


def _selector(
    domain: CommunicationDomain,
    unit_type: str,
    meaning: str,
    *,
    status: str | None = None,
    polarity: str | None = None,
    profile_id: CommunicationProfileId = CommunicationProfileId.NATO_MILITARY,
) -> PilotSelector:
    return PilotSelector(
        profile_id=profile_id,
        domain=domain,
        unit_type=unit_type,
        semantic_meaning=meaning,
        status=status,
        polarity=polarity,
    )


def _slot(
    placeholder: str,
    semantic_key: str,
    kind: ProtectedValueKind,
    formatter: PilotFormatterId,
    unit: str | None = None,
) -> PilotSlotDefinition:
    return PilotSlotDefinition(
        placeholder=placeholder,
        semantic_key=semantic_key,
        expected_kind=kind,
        expected_unit=unit,
        formatter_id=formatter,
    )


def _entry(
    entry_id: str,
    selector: PilotSelector,
    en_us: str,
    ru_ru: str,
    *slots: PilotSlotDefinition,
) -> PilotPhraseologyEntry:
    return PilotPhraseologyEntry(
        entry_id=entry_id,
        catalog_version=CATALOG_VERSION,
        selector=selector,
        slots=slots,
        realizations=(
            PilotLanguageRealization(language="en-US", template=en_us),
            PilotLanguageRealization(language="ru-RU", template=ru_ru),
        ),
    )


def build_pilot_phraseology_catalog() -> PilotPhraseologyCatalog:
    """Return the complete 29-entry experimental/non-normative Pilot catalog."""

    general = CommunicationDomain.GENERAL
    navigation = CommunicationDomain.NAVIGATION
    mission_control = CommunicationDomain.MISSION_CONTROL
    atc = CommunicationDomain.ATC
    entries = (
        _entry(
            "general-acknowledgement",
            _selector(
                general,
                "general.response",
                "general.acknowledgement",
                status="accepted",
                polarity="positive",
            ),
            "Roger.",
            "Принято.",
        ),
        _entry(
            "general-affirmative",
            _selector(
                general,
                "general.response",
                "general.affirmative",
                status="confirmed",
                polarity="positive",
            ),
            "Affirmative.",
            "Так точно.",
        ),
        _entry(
            "general-negative",
            _selector(
                general,
                "general.response",
                "general.negative",
                status="rejected",
                polarity="negative",
            ),
            "Negative.",
            "Никак нет.",
        ),
        _entry(
            "general-unable",
            _selector(
                general,
                "general.response",
                "general.unable",
                status="unavailable",
                polarity="negative",
            ),
            "Unable.",
            "Не могу выполнить.",
        ),
        _entry(
            "general-information-unavailable",
            _selector(
                general,
                "general.response",
                "general.information_unavailable",
                status="unavailable",
            ),
            "Information unavailable.",
            "Информация недоступна.",
        ),
        _entry(
            "general-say-again",
            _selector(
                general,
                "general.response",
                "general.say_again",
                status="clarification_required",
            ),
            "Say again.",
            "Повторите.",
        ),
        _entry(
            "general-say-again-fap",
            _selector(
                general,
                "general.response",
                "general.say_again",
                status="clarification_required",
                profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
            ),
            "Say again.",
            "Повторите.",
        ),
        _entry(
            "general-readback-confirmed",
            _selector(
                general,
                "general.response",
                "general.readback_confirmed",
                status="confirmed",
                polarity="positive",
            ),
            "Readback correct.",
            "Повторение правильное.",
        ),
        _entry(
            "radio-callsign",
            _selector(general, "radio.identity", "radio.callsign", status="available"),
            "Callsign {callsign}.",
            "Позывной {callsign}.",
            _slot(
                "callsign",
                "radio.callsign",
                ProtectedValueKind.CALLSIGN,
                PilotFormatterId.EXACT_TEXT,
            ),
        ),
        _entry(
            "radio-frequency",
            _selector(
                general, "radio.frequency", "radio.frequency", status="available"
            ),
            "Frequency {frequency} megahertz.",
            "Частота {frequency} мегагерца.",
            _slot(
                "frequency",
                "radio.frequency_mhz",
                ProtectedValueKind.FREQUENCY,
                PilotFormatterId.FIXED_THREE,
                "MHz",
            ),
        ),
        _entry(
            "radio-modulation",
            _selector(
                general,
                "radio.modulation",
                "radio.modulation",
                status="available",
            ),
            "Modulation {modulation}.",
            "Модуляция {modulation}.",
            _slot(
                "modulation",
                "radio.modulation",
                ProtectedValueKind.GENERIC,
                PilotFormatterId.MODULATION_EXACT,
            ),
        ),
        _entry(
            "radio-frequency-modulation",
            _selector(
                general,
                "radio.channel",
                "radio.frequency_modulation",
                status="available",
            ),
            "Frequency {frequency} megahertz, {modulation}.",
            "Частота {frequency} мегагерца, модуляция {modulation}.",
            _slot(
                "frequency",
                "radio.frequency_mhz",
                ProtectedValueKind.FREQUENCY,
                PilotFormatterId.FIXED_THREE,
                "MHz",
            ),
            _slot(
                "modulation",
                "radio.modulation",
                ProtectedValueKind.GENERIC,
                PilotFormatterId.MODULATION_EXACT,
            ),
        ),
        _entry(
            "navigation-heading",
            _selector(
                navigation,
                "navigation.heading",
                "navigation.heading",
                status="available",
            ),
            "Heading {heading} degrees.",
            "Курс {heading} градусов.",
            _slot(
                "heading",
                "ownship.heading_deg",
                ProtectedValueKind.HEADING,
                PilotFormatterId.INTEGER,
                "deg",
            ),
        ),
        _entry(
            "navigation-altitude",
            _selector(
                navigation,
                "navigation.altitude",
                "navigation.altitude",
                status="available",
            ),
            "Altitude {altitude} feet.",
            "Высота {altitude} футов.",
            _slot(
                "altitude",
                "ownship.altitude_ft",
                ProtectedValueKind.ALTITUDE,
                PilotFormatterId.INTEGER,
                "ft",
            ),
        ),
        _entry(
            "navigation-speed",
            _selector(
                navigation,
                "navigation.speed",
                "navigation.speed",
                status="available",
            ),
            "Speed {speed} knots.",
            "Скорость {speed} узлов.",
            _slot(
                "speed",
                "ownship.speed_kt",
                ProtectedValueKind.SPEED,
                PilotFormatterId.INTEGER,
                "kt",
            ),
        ),
        _entry(
            "navigation-range",
            _selector(
                navigation,
                "navigation.range",
                "navigation.range",
                status="available",
            ),
            "Range {distance} nautical miles.",
            "Дальность {distance} морских миль.",
            _slot(
                "distance",
                "navigation.range_nm",
                ProtectedValueKind.GENERIC,
                PilotFormatterId.INTEGER,
                "nm",
            ),
        ),
        _entry(
            "navigation-bearing",
            _selector(
                navigation,
                "navigation.bearing",
                "navigation.bearing",
                status="available",
            ),
            "Bearing {bearing} degrees.",
            "Пеленг {bearing} градусов.",
            _slot(
                "bearing",
                "navigation.bearing_deg",
                ProtectedValueKind.GENERIC,
                PilotFormatterId.INTEGER,
                "deg",
            ),
        ),
        _entry(
            "navigation-signed-correction",
            _selector(
                navigation,
                "navigation.correction",
                "navigation.signed_correction",
                status="available",
            ),
            "Correction {offset} feet.",
            "Поправка {offset} футов.",
            _slot(
                "offset",
                "navigation.vertical_offset_ft",
                ProtectedValueKind.GENERIC,
                PilotFormatterId.SIGNED_INTEGER,
                "ft",
            ),
        ),
        _entry(
            "navigation-tacan-available",
            _selector(
                navigation,
                "navigation.tacan",
                "navigation.tacan",
                status="available",
            ),
            "TACAN {tacan}.",
            "ТАКАН {tacan}.",
            _slot(
                "tacan",
                "navigation.tacan_channel",
                ProtectedValueKind.TACAN,
                PilotFormatterId.TACAN_EXACT,
            ),
        ),
        _entry(
            "navigation-tacan-unavailable",
            _selector(
                navigation,
                "navigation.tacan",
                "navigation.tacan",
                status="unavailable",
            ),
            "TACAN unavailable.",
            "ТАКАН недоступен.",
        ),
        _entry(
            "jtac-laser-code",
            _selector(
                CommunicationDomain.JTAC,
                "jtac.laser_code",
                "jtac.laser_code",
                status="available",
            ),
            "Laser code {laser_code}.",
            "Код лазера {laser_code}.",
            _slot(
                "laser_code",
                "jtac.laser_code",
                ProtectedValueKind.LASER_CODE,
                PilotFormatterId.LASER_CODE_EXACT,
            ),
        ),
        _entry(
            "navigation-position",
            _selector(
                navigation,
                "navigation.position",
                "navigation.position",
                status="available",
            ),
            "Position latitude {latitude} degrees, longitude {longitude} degrees.",
            "Позиция: широта {latitude} градуса, долгота {longitude} градуса.",
            _slot(
                "latitude",
                "ownship.position.latitude",
                ProtectedValueKind.COORDINATES,
                PilotFormatterId.COORDINATE_SIX,
                "deg",
            ),
            _slot(
                "longitude",
                "ownship.position.longitude",
                ProtectedValueKind.COORDINATES,
                PilotFormatterId.COORDINATE_SIX,
                "deg",
            ),
        ),
        _entry(
            "warning-fuel-low",
            _selector(
                mission_control,
                "mission_control.warning",
                "mission_control.fuel_low",
                status="warning",
            ),
            "Warning, fuel low.",
            "Предупреждение: малый остаток топлива.",
        ),
        _entry(
            "warning-traffic",
            _selector(
                mission_control,
                "mission_control.warning",
                "mission_control.traffic",
                status="warning",
            ),
            "Warning, traffic.",
            "Предупреждение: воздушное движение.",
        ),
        _entry(
            "status-ready",
            _selector(
                general,
                "general.status",
                "general.ready",
                status="ready",
                polarity="positive",
            ),
            "Status ready.",
            "Статус: готов.",
        ),
        _entry(
            "status-not-ready",
            _selector(
                general,
                "general.status",
                "general.not_ready",
                status="not_ready",
                polarity="negative",
            ),
            "Status not ready.",
            "Статус: не готов.",
        ),
        _entry(
            "atc-takeoff-clearance-granted",
            _selector(
                atc,
                "atc.takeoff",
                "atc.takeoff_clearance_granted",
                status="granted",
                polarity="positive",
                profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
            ),
            "{callsign}, runway {runway}, cleared for takeoff.",
            "{callsign}, полоса {runway}, взлёт разрешён.",
            _slot(
                "callsign",
                "atc.callsign",
                ProtectedValueKind.CALLSIGN,
                PilotFormatterId.EXACT_TEXT,
            ),
            _slot(
                "runway",
                "atc.runway_id",
                ProtectedValueKind.RUNWAY,
                PilotFormatterId.EXACT_TEXT,
            ),
        ),
        _entry(
            "atc-takeoff-hold",
            _selector(
                atc,
                "atc.takeoff",
                "atc.takeoff_hold",
                status="hold",
                polarity="negative",
                profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
            ),
            "{callsign}, hold position, runway {runway}.",
            "{callsign}, сохраняйте позицию, полоса {runway}.",
            _slot(
                "callsign",
                "atc.callsign",
                ProtectedValueKind.CALLSIGN,
                PilotFormatterId.EXACT_TEXT,
            ),
            _slot(
                "runway",
                "atc.runway_id",
                ProtectedValueKind.RUNWAY,
                PilotFormatterId.EXACT_TEXT,
            ),
        ),
        _entry(
            "atc-takeoff-context-unavailable",
            _selector(
                atc,
                "atc.takeoff",
                "atc.takeoff_context_unavailable",
                status="unavailable",
                profile_id=CommunicationProfileId.FAP_RUSSIAN_ATC,
            ),
            "{callsign}, takeoff clearance unavailable, runway {runway}.",
            "{callsign}, разрешение на взлёт недоступно, полоса {runway}.",
            _slot(
                "callsign",
                "atc.callsign",
                ProtectedValueKind.CALLSIGN,
                PilotFormatterId.EXACT_TEXT,
            ),
            _slot(
                "runway",
                "atc.runway_id",
                ProtectedValueKind.RUNWAY,
                PilotFormatterId.EXACT_TEXT,
            ),
        ),
    )
    if len(entries) != 29:
        raise AssertionError("bounded Pilot catalog must contain exactly 29 entries")
    return PilotPhraseologyCatalog(entries=entries)
