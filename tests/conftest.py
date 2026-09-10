"""Existing host replays never open the newly optional Interpreter transport.

The dedicated IA integration tests replace this boundary with the real owner
and fake protocol wire explicitly. No production readiness behavior is mocked.
"""
import pytest


@pytest.fixture(autouse=True)
def offline_optional_interpreter(monkeypatch):
    import orion.full_voice_service as host
    from orion.conversational_contracts import ConversationFailure
    from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter

    class Unavailable(WarmYandexAircraftInterpreter):
        @classmethod
        def configured(cls, *args, **kwargs): return cls(lambda: pytest.fail("offline network forbidden"))
        async def prepare(self): return False
        async def interpret(self, request, cancellation):
            raise ConversationFailure("interpreter_not_warm")
        async def interpret_general(self, request, cancellation):
            raise ConversationFailure("interpreter_not_warm")
        async def shutdown(self): pass

    monkeypatch.setattr(host, "WarmYandexAircraftInterpreter", Unavailable)
