"""Concrete task selection must not dispatch an incomplete chat request."""

import pytest

from ui import app, components
from core.engineering_requirements import route_engineering_evidence_requirement


class State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self[name] = value


class Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Rerun(Exception):
    pass


def rerun():
    raise Rerun


def test_clicking_card_only_selects_workflow_without_sending_question(monkeypatch):
    state = State(api_available=True)
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(app.st, "columns", lambda *args, **kwargs: [Context(), Context()])
    monkeypatch.setattr(app.st, "button", lambda *args, **kwargs: kwargs.get("key") == "starter_0")
    monkeypatch.setattr(app.st, "rerun", rerun)
    with pytest.raises(Rerun):
        app._render_starter_prompt_prompts("engineering")
    assert state.selected_core_workflow == "configuration"
    assert "pending_starter_question" not in state


@pytest.mark.parametrize("workflow,subject,reference,valid,profile", [
    ("configuration", "", "settings.py", False, None),
    ("change_test", "   ", "", False, None),
    ("docs_code", "README.md", "", False, None),
    ("configuration", "SUPPORT_RESULT_LIMIT", "support_search/settings.py", True, "DIAGNOSIS_SINGLE_V1"),
    ("change_test", "support_search/settings.py", "", True, "CHANGE_TEST_V1"),
    ("docs_code", "README.md", "support_search/settings.py", True, "DOCS_CODE_V1"),
])
def test_form_requires_targets_and_dispatches_the_existing_evidence_task(
    monkeypatch, workflow, subject, reference, valid, profile,
):
    state = State(api_available=True)
    warnings = []
    fields = iter([subject, reference])
    monkeypatch.setattr(app.st, "session_state", state)
    monkeypatch.setattr(app.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(app.st, "form", lambda *args, **kwargs: Context())
    monkeypatch.setattr(app.st, "text_input", lambda *args, **kwargs: next(fields))
    monkeypatch.setattr(app.st, "form_submit_button", lambda *args, **kwargs: True)
    monkeypatch.setattr(app.st, "warning", warnings.append)
    monkeypatch.setattr(app.st, "rerun", rerun)
    if valid:
        with pytest.raises(Rerun):
            app._render_core_workflow_form(workflow)
        question = state.pending_starter_question
        assert subject in question
        if reference:
            assert reference in question
        requirement = route_engineering_evidence_requirement(question)
        assert requirement.requirement_profile.value == profile
        assert warnings == []
    else:
        app._render_core_workflow_form(workflow)
        assert "pending_starter_question" not in state
        assert len(warnings) == 1


def test_incomplete_or_unknown_workflow_has_no_dispatch_payload():
    assert components.build_core_workflow_question("unknown", "target") is None
    assert components.build_core_workflow_question("docs_code", "README.md", "   ") is None
