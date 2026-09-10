"""Keep historical tranche budgets separate from the approved Level-0 baseline.

The four committed additions are grandfathered ONLY up to the immutable SHA.
They are not a working-tree allowlist. Candidate envelope is explicitly scoped
below; the separately authorized STT input correction is bounded to eligibility.
The c444860 differential test freezes output policy and all other Core symbols.
"""
import ast
from pathlib import Path
import subprocess

BASELINE = "9ccab967dfe018f29302fb87e8105a4bb11a89de"
ADDED_AT_BASELINE = {
    "orion/conversational_contracts.py", "orion/conversational_core.py",
    "orion/conversational_presentation.py", "orion/yandex_realtime_text_conversation.py",
}
CURRENT_SCOPE = {"orion/yandex_realtime_text_conversation.py", "orion/conversational_core.py",
    "orion/conversational_presentation.py", "orion/full_voice_service.py",
    "orion/hybrid_aircraft_core.py", "orion/realtime_test_evidence.py"}


def assert_candidate_core_scope(before: str, after: str):
    original, current = ast.parse(before), ast.parse(after)
    # The 2026-09-09 user explicitly replaced phrase admission and extended the
    # closed input slice. On 2026-09-10 only STT eligibility was authorized.
    # Ledger, binding, expiry and exact text remain frozen. The independent
    # c444860 differential in test_conversation_stt_routing freezes output too.
    def policy_node(n):
        return (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
            or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {
                "_INPUT", "_CLAUSES", "_SOCIAL_CLAUSE", "_DISCOURSE_MODIFIERS"} for t in n.targets)
            or isinstance(n, ast.FunctionDef) and n.name in {"admit_social_text", "eligible_conversation"})
    original.body = [n for n in original.body if not policy_node(n)]
    current.body = [n for n in current.body if not policy_node(n)]
    additions = [n for n in current.body if isinstance(n, ast.FunctionDef) and n.name == "normalize_candidate_envelope"]
    assert len(additions) == 1
    current.body.remove(additions[0])
    wrappers = [n for n in ast.walk(current) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "normalize_candidate_envelope"]
    assert len(wrappers) == 1 and ast.dump(wrappers[0].args[0]) == ast.dump(ast.Name(id="text", ctx=ast.Load()))
    # Restore ONLY the authorized JSON argument to compare every other symbol.
    calls = [n for n in ast.walk(current) if isinstance(n, ast.Call) and n.args and n.args[0] is wrappers[0]]
    assert len(calls) == 1 and ast.unparse(calls[0].func) == "json.loads"
    calls[0].args[0] = wrappers[0].args[0]
    assert ast.dump(current) == ast.dump(original), "Core outside candidate envelope changed"


def assert_deltas(historical: set[str], current: set[str], untracked: set[str], historical_scope: set[str]):
    assert historical - ADDED_AT_BASELINE <= historical_scope
    assert current <= CURRENT_SCOPE, f"Unauthorized current production delta: {current - CURRENT_SCOPE}"
    assert not untracked, f"Untracked production additions: {untracked}"


def assert_historical_and_current_scope(root: Path, historical_base: str, historical_scope: set[str]):
    def names(*args):
        return set(subprocess.check_output(["git", *args, "--", "orion", "packaging", "dcs-export"], cwd=root).decode().splitlines())
    # Verify that the exception really is the four added files in the approved
    # preservation commit; it cannot silently grandfather another later change.
    added = names("diff", BASELINE + "^", BASELINE, "--diff-filter=A", "--name-only")
    assert added == ADDED_AT_BASELINE
    from ia_scope_guard import ADDED, HUNKS, verify_ia_scope
    verify_ia_scope()
    assert_deltas(names("diff", historical_base, BASELINE, "--name-only"),
                  names("diff", BASELINE, "--name-only") - HUNKS.keys() - ADDED,
                  names("ls-files", "--others", "--exclude-standard") - ADDED, historical_scope)
    original = subprocess.check_output(["git", "show", BASELINE + ":orion/conversational_core.py"], cwd=root).decode("utf-8")
    assert_candidate_core_scope(original, (root / "orion/conversational_core.py").read_text(encoding="utf-8"))
