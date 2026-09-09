"""Bounded input eligibility and non-authoritative conversation finalization.

Structural validity is NOT factual validation. Conversation owns no facts,
tools or actions. The provider authors the complete reply; Core never rewrites
it. Hallucination risk is accepted, not disguised as a semantic guarantee.
"""
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re

from orion.conversational_contracts import (
    ConversationalCandidate, ConversationalRequest, ConversationFailure,
    FinalizedConversationalText, SocialDraft,
)


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalized(text: str) -> str:
    return " ".join(text.casefold().replace("ё", "е").split())


# Meaning-bearing constituents remain ordered and must consume the entire input.
# Only the three bounded discourse/time modifiers below may move between them.
# This is a local social class recognizer, not UNKNOWN -> Conversation.
_SOCIAL_CLAUSE = re.compile(
    r"(?:полет (?:тяжело идет|идет тяжело)|"
    r"полеты (?:тяжело идут|идут тяжело)|"
    r"(?:непросто|тяжело) летится|"
    r"я не в форме|все идет тяжеловато|все тяжеловато|"
    r"давно я нормально не летал[а]?|не мой день)"
)
_DISCOURSE_MODIFIERS = frozenset({"чтото", "както", "сегодня"})


def eligible_conversation(text: str) -> bool:
    """Recognize bounded ASR variation without rewriting the submitted source.

    Retain negation, pronouns, inflection and every unknown word. Quotes,
    questions, symbols and multiple sentences are not silently discarded.
    Hyphen/space loss is supported only for the known discourse particles.
    """
    if not text or len(text) > 500:
        return False
    value = normalized(text)
    value = re.sub(r"[.!]+$", "", value)
    value = re.sub(r"\b(что|как)(?:[-‐‑–]| )?то\b", r"\1то", value)
    if re.fullmatch(r"[а-я]+(?:[ ,]+[а-я]+)*", value) is None:
        return False
    tokens = value.replace(",", " ").split()
    # Removing at most one occurrence of each *non-operational* modifier allows
    # mild word-order variation, not a bag-of-words match of meaningful content.
    if any(tokens.count(modifier) > 1 for modifier in _DISCOURSE_MODIFIERS):
        return False
    clause = " ".join(token for token in tokens if token not in _DISCOURSE_MODIFIERS)
    return _SOCIAL_CLAUSE.fullmatch(clause) is not None


def admit_social_text(text: str) -> bool:
    """Russian text shape only; neither semantic certification nor authority."""
    return (isinstance(text, str) and 0 < len(text) <= 300
        and re.search(r"[А-Яа-яЁё]", text) is not None
        and re.search(r'[^А-Яа-яЁё0-9 \t\r\n,.!?—–:;…«»"()\-]', text) is None)


def normalize_candidate_envelope(text: str) -> str:
    """One whole-message fence only; return exact JSON body, never rewrite it."""
    if not isinstance(text, str) or not 0 < len(text) <= 4096:
        raise ConversationFailure("invalid_candidate_envelope")
    if "```" not in text:
        return text
    match = re.fullmatch(r"[ \t\r\n]*```(?:json)?[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n```[ \t\r\n]*", text)
    if match is None or "```" in match["body"] or not match["body"].strip():
        raise ConversationFailure("invalid_candidate_envelope")
    return match["body"]


def parse_draft(text: str) -> SocialDraft:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConversationFailure("duplicate_candidate_key")
            result[key] = value
        return result
    try:
        return SocialDraft.model_validate(json.loads(normalize_candidate_envelope(text), object_pairs_hook=unique), strict=True)
    except Exception:
        raise ConversationFailure("invalid_candidate_schema") from None


class ConversationalCore:
    """Turn-scoped admission ledger. No world, gateway, planner or radio owner."""
    def __init__(self, *, clock=lambda: datetime.now(UTC)):
        self.clock = clock
        self._requests = {}
        self._finalized = {}

    def request(self, utterance):
        if utterance.input_language != "ru-RU" or not eligible_conversation(utterance.text):
            return None
        identity = utterance.interaction_id
        previous = self._requests.get(identity)
        if previous is not None:
            if previous.source_text != utterance.text:
                raise ConversationFailure("conflicting_replay")
            return previous
        if len(self._requests) >= 64:
            raise ConversationFailure("conversation_capacity")
        request = ConversationalRequest(interaction_id=identity, source_text=utterance.text,
            source_sha256=source_hash(utterance.text), deadline=self.clock() + timedelta(seconds=12))
        self._requests[identity] = request
        return request

    def admit(self, candidate: ConversationalCandidate) -> FinalizedConversationalText:
        if type(candidate) is not ConversationalCandidate:
            raise ConversationFailure("typed_candidate_required")
        try:
            checked = ConversationalCandidate.model_validate(candidate.model_dump(), strict=True)
            request = checked.request
            if (self._requests.get(request.interaction_id) != request
                or request.source_sha256 != source_hash(request.source_text)
                or request.deadline.tzinfo is None or self.clock() >= request.deadline
                or not admit_social_text(checked.draft.text)):
                raise ValueError
        except Exception:
            raise ConversationFailure("candidate_not_admitted") from None
        finalized = FinalizedConversationalText(candidate=checked, text=checked.draft.text)
        previous = self._finalized.get(request.interaction_id)
        if previous is not None and previous != finalized:
            raise ConversationFailure("conflicting_replay")
        self._finalized[request.interaction_id] = finalized
        return finalized

    def authorize(self, finalized):
        return (type(finalized) is FinalizedConversationalText
            and self._finalized.get(finalized.candidate.request.interaction_id) == finalized
            and finalized.text == finalized.candidate.draft.text
            and self.clock() < finalized.candidate.request.deadline
            and admit_social_text(finalized.text))
