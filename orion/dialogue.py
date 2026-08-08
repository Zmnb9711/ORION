from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DialogueLanguage(StrEnum):
    AUTO = "auto"
    RU = "ru"
    EN = "en"


class DialogueIntent(StrEnum):
    STATUS = "status"
    THREATS = "threats"
    AWACS = "awacs"
    TANKER = "tanker"
    LASER = "laser"
    SMOKE = "smoke"
    SMALL_TALK = "small_talk"
    UNKNOWN = "unknown"


class DialogueRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    language: DialogueLanguage = DialogueLanguage.AUTO


class DialogueResult(BaseModel):
    language: DialogueLanguage
    intent: DialogueIntent
    confidence: float = Field(ge=0, le=1)
    requires_confirmation: bool = False
    reply: str


_RU_MARKERS = ("что", "где", "запрос", "угроз", "топлив", "дозаправ", "лазер", "дым", "привет", "как дела", "предконтакт")
_EN_MARKERS = ("what", "where", "request", "threat", "fuel", "tanker", "refuel", "aar", "pre-contact", "precontact", "laser", "smoke", "hello", "how are")


def detect_language(text: str) -> DialogueLanguage:
    lowered = text.lower()
    ru_score = sum(marker in lowered for marker in _RU_MARKERS)
    en_score = sum(marker in lowered for marker in _EN_MARKERS)
    if ru_score > en_score:
        return DialogueLanguage.RU
    if en_score > ru_score:
        return DialogueLanguage.EN
    return DialogueLanguage.RU if any("а" <= char <= "я" or char == "ё" for char in lowered) else DialogueLanguage.EN


def classify_dialogue(request: DialogueRequest) -> DialogueResult:
    language = detect_language(request.text) if request.language == DialogueLanguage.AUTO else request.language
    text = request.text.lower()

    intents: list[tuple[DialogueIntent, tuple[str, ...], bool]] = [
        (DialogueIntent.LASER, ("лазер", "подсвет", "laser", "lase"), True),
        (DialogueIntent.SMOKE, ("дым", "smoke", "mark with smoke"), True),
        (DialogueIntent.TANKER, ("дозаправ", "танкер", "tanker", "refuel", "aerial refuel", "aar", "fuel", "pre-contact", "precontact", "предконтакт"), False),
        (DialogueIntent.AWACS, ("дрло", "авакс", "awacs", "picture"), False),
        (DialogueIntent.THREATS, ("угроз", "контакт", "threat", "bogey", "bandit"), False),
        (DialogueIntent.STATUS, ("статус", "состояние", "параметр", "status", "state", "altitude", "speed"), False),
        (DialogueIntent.SMALL_TALK, ("привет", "как дела", "погода", "hello", "how are", "nice weather"), False),
    ]

    for intent, markers, confirmation in intents:
        if any(marker in text for marker in markers):
            return DialogueResult(
                language=language,
                intent=intent,
                confidence=0.9,
                requires_confirmation=confirmation,
                reply=_reply(language, intent, confirmation),
            )

    return DialogueResult(
        language=language,
        intent=DialogueIntent.UNKNOWN,
        confidence=0.2,
        reply=(
            "Не удалось уверенно определить запрос. Уточните задачу."
            if language == DialogueLanguage.RU
            else "I could not determine the request confidently. Please clarify."
        ),
    )


def _reply(language: DialogueLanguage, intent: DialogueIntent, confirmation: bool) -> str:
    ru = {
        DialogueIntent.STATUS: "Запрос состояния принят.",
        DialogueIntent.THREATS: "Подготавливаю картину угроз.",
        DialogueIntent.AWACS: "Запрос данных ДРЛО принят.",
        DialogueIntent.TANKER: "Запрос информации о дозаправщике принят.",
        DialogueIntent.LASER: "Для лазерного целеуказания требуется подтверждение и конкретная цель.",
        DialogueIntent.SMOKE: "Для дымовой маркировки требуется подтверждение и конкретная цель.",
        DialogueIntent.SMALL_TALK: "На связи. Продолжаю следить за обстановкой.",
    }
    en = {
        DialogueIntent.STATUS: "Aircraft status request accepted.",
        DialogueIntent.THREATS: "Preparing the threat picture.",
        DialogueIntent.AWACS: "AWACS information request accepted.",
        DialogueIntent.TANKER: "Tanker information request accepted.",
        DialogueIntent.LASER: "Laser designation requires confirmation and a specific target.",
        DialogueIntent.SMOKE: "Smoke marking requires confirmation and a specific target.",
        DialogueIntent.SMALL_TALK: "Standing by. I am continuing to monitor the situation.",
    }
    messages = ru if language == DialogueLanguage.RU else en
    return messages[intent]
