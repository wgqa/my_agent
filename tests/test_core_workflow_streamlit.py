"""Exercise the actual starter cards and form widgets without model calls."""

from streamlit.testing.v1 import AppTest


SCRIPT = '''
import streamlit as st
from ui.app import _render_starter_prompt_prompts
st.session_state.api_available = True
_render_starter_prompt_prompts("engineering")
if "pending_starter_question" in st.session_state:
    st.write(st.session_state.pending_starter_question)
'''


def test_configuration_card_requires_input_before_preparing_question():
    at = AppTest.from_string(SCRIPT).run()
    assert not at.exception
    at.button(key="starter_0").click().run()
    assert not at.exception
    assert "pending_starter_question" not in at.session_state
    at.button[-1].click().run()
    assert len(at.warning) == 1
    assert "pending_starter_question" not in at.session_state
    at.text_input(key="core_subject_configuration").set_value("SUPPORT_RESULT_LIMIT")
    at.text_input(key="core_reference_configuration").set_value("support_search/settings.py")
    at.button[-1].click().run()
    assert not at.exception
    assert "SUPPORT_RESULT_LIMIT" in at.session_state.pending_starter_question
    assert "support_search/settings.py" in at.session_state.pending_starter_question


def test_document_card_requires_both_sources():
    at = AppTest.from_string(SCRIPT).run()
    at.button(key="starter_2").click().run()
    at.text_input(key="core_subject_docs_code").set_value("README.md")
    at.button[-1].click().run()
    assert len(at.warning) == 1
    assert "pending_starter_question" not in at.session_state
    at.text_input(key="core_reference_docs_code").set_value("support_search/settings.py")
    at.button[-1].click().run()
    assert not at.exception
    assert "README.md" in at.session_state.pending_starter_question
    assert "support_search/settings.py" in at.session_state.pending_starter_question
