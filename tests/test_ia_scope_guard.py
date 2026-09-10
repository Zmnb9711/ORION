import pytest
from ia_scope_guard import HUNKS, ROOT, restore_ia, verify_ia_scope


def test_only_reviewed_handoff_and_no_other_production_changes():
    verify_ia_scope()


@pytest.mark.parametrize("path", sorted(HUNKS))
def test_even_one_unreviewed_mutation_in_or_outside_handoff_is_rejected(path):
    text = (ROOT/path).read_text(encoding="utf-8")
    with pytest.raises(AssertionError):
        restore_ia(path, text + "\n# unreviewed change\n")
    hunk = HUNKS[path][0]["after"]
    with pytest.raises(AssertionError):
        restore_ia(path, text.replace(hunk, hunk + "# unreviewed handoff\n", 1))
