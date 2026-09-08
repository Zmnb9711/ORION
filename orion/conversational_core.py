"""Closed subjective-input eligibility and positive Level-0 semantic language.

This is NOT a general prose safety classifier. The provider authors the complete
reply; every clause must belong to a non-operational social construction. No
unknown prose is admitted by absence of blacklist words. Core never rewrites it.
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


_INPUT = re.compile(
    r"(?:(?:что-то )?(?:сегодня )?полет (?:тяжело идет|идет тяжело)|"
    r"сегодня (?:как-то )?(?:непросто|тяжело) летится|"
    r"(?:что-то )?я сегодня не в форме|что-то сегодня все идет тяжеловато)[.!]?"
)


def eligible_conversation(text: str) -> bool:
    return len(text) <= 500 and _INPUT.fullmatch(normalized(text)) is not None


# Positive semantic productions, not forbidden-word matching. They express only
# empathy, generic difficult-day acknowledgement and invitation to TALK.
# Advice (including "не торопитесь"), diagnoses and reassurance of safety have
# no production. No free-text slot can smuggle in another assertion.
_CLAUSES = (
    r"(?:да, )?(?:понимаю(?: вас)?|сочувствую(?: вам)?|такое бывает|бывает)",
    r"(?:да, )?бывают (?:и )?(?:такие|непростые|трудные) дни",
    r"(?:похоже|кажется), (?:у вас )?(?:сегодня )?(?:непростой|трудный|тяжелый) день",
    r"(?:похоже|кажется), сегодня (?:вам )?все дается (?:непросто|тяжелее обычного)",
    r"звучит как (?:непростой|трудный|тяжелый) день",
    r"(?:да, )?(?:иногда|бывает, что) (?:все )?дается (?:непросто|тяжелее обычного)",
    r"хотите (?:об этом )?поговорить",
    r"(?:я )?(?:готова вас выслушать|на связи)",
)


def admit_social_text(text: str) -> bool:
    if not 0 < len(text) <= 300 or re.search(r"[^А-Яа-яЁё\s,.!?—-]", text):
        return False
    # No hyphen/dash production, quotation, arbitrary suffix or unmatched word.
    clauses = re.split(r"[.!?]", normalized(text))
    if clauses[-1] == "":
        clauses.pop()
    if not 1 <= len(clauses) <= 3:
        return False
    return all(any(re.fullmatch(pattern, clause.strip()) for pattern in _CLAUSES) for clause in clauses)


def parse_draft(text: str) -> SocialDraft:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ConversationFailure("duplicate_candidate_key")
            result[key] = value
        return result
    try:
        return SocialDraft.model_validate(json.loads(text, object_pairs_hook=unique), strict=True)
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
