"""Mechanical differential: only the approved host seam and evidence projection."""
import ast
from pathlib import Path
import subprocess

BASE = "f346e13f879a7845ad2ffa24ee6360afd8ebde70"


def baseline(path):
    return ast.parse(subprocess.check_output(["git", "show", BASE + ":" + path]).decode("utf-8"))


def test_literal_host_lifecycle_with_only_conversation_handoff():
    path = "orion/full_voice_service.py"
    current = ast.parse(Path(path).read_text(encoding="utf-8"))
    class Restore(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module in {"orion.conversational_core", "orion.conversational_presentation", "orion.hybrid_aircraft_contracts"}:
                return None
            return node
        def visit_FunctionDef(self, node):
            if node.name == "observe_conversation": return None
            return self.generic_visit(node)
        def visit_If(self, node):
            if ast.unparse(node.test) == "information.route is HybridRoute.UNSUPPORTED and information.failure is None":
                return None
            return self.generic_visit(node)
        def visit_Expr(self, node):
            if isinstance(node.value, ast.Call) and ast.unparse(node.value.func) == "observe_conversation":
                assert ast.unparse(node.value.args[0]) == "'physical_turn_end'"
                return None
            return node
    assert ast.dump(Restore().visit(current)) == ast.dump(baseline(path))


def test_existing_evidence_recorder_unchanged_outside_new_projection():
    path = "orion/realtime_test_evidence.py"
    current = ast.parse(Path(path).read_text(encoding="utf-8"))
    recorder = next(n for n in current.body if isinstance(n, ast.ClassDef) and n.name == "RealtimeTestEvidenceRecorder")
    added = next(n for n in recorder.body if isinstance(n, ast.FunctionDef) and n.name == "record_conversation_slice")
    recorder.body.remove(added)
    assert ast.dump(current) == ast.dump(baseline(path))


def test_presentation_admission_cancel_and_shutdown_unchanged():
    path = "orion/conversational_presentation.py"
    before, after = baseline(path), ast.parse(Path(path).read_text(encoding="utf-8"))
    def named(tree, name):
        return next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    assert ast.dump(named(before, "ConversationalPresentation")) == ast.dump(named(after, "ConversationalPresentation"))
    for name in ("__init__", "shutdown"):
        methods = [next(n for n in named(t, "ConversationVoice").body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name) for t in (before, after)]
        assert ast.dump(methods[0]) == ast.dump(methods[1])


def test_terminal_observer_cannot_change_protocol_control_or_keep_resources():
    path = "orion/yandex_realtime_text_conversation.py"
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    observer = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_observe_terminal")
    assert not any(isinstance(n, (ast.Await, ast.Return, ast.Assign)) for n in ast.walk(observer))
    from orion.yandex_realtime_text_conversation import TextConversationProvider
    p = TextConversationProvider(lambda: None, observe=lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    p._observe_terminal("bad envelope", turn_id="test")
    assert not p.owned and not p.used and not p.busy
