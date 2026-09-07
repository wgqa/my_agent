"""Central Streamlit theme for the Engineering Agent product shell.

All CSS lives here so ``app.py`` stays structural. The visual system is a
compact developer-tool scheme: neutral borders, muted metadata, monospace
snippets, and status chips that never rely on color alone.
"""

from __future__ import annotations

import streamlit as st


CSS = """
<style>
/* ---------- layout primitives ---------- */
[data-testid="stSidebar"] { border-right: 1px solid rgba(120, 130, 145, .16); }
[data-testid="stSidebar"] .block-container { padding-top: 1.6rem; }
.block-container { padding-top: 2.2rem; max-width: 78rem; }

/* ---------- sidebar product mark ---------- */
.product-mark-kicker { font-size: .68rem; letter-spacing: .14em; text-transform: uppercase; color: #8a94a3; }
.product-mark-title { font-size: 1.28rem; font-weight: 700; letter-spacing: .01em; margin: .1rem 0 .05rem; color: #1d2a36; }
.product-mark-sub { font-size: .78rem; color: #69768a; margin-bottom: 1.0rem; }

/* ---------- sidebar section headers ---------- */
.sidebar-section { font-size: .68rem; letter-spacing: .12em; text-transform: uppercase; color: #8a94a3; margin: 1.1rem 0 .3rem; }

/* ---------- conversation list ---------- */
.active-conversation {
    background: rgba(70, 90, 110, .11);
    border-radius: 7px; padding: .5rem .7rem; margin: .12rem 0;
    font-size: .88rem; color: #1d2a36;
}
.conversation-item { font-size: .88rem; }
.sidebar-spacer { min-height: 6vh; }

/* ---------- workspace status chips ---------- */
.workspace-row { display: flex; align-items: center; gap: .4rem; font-size: .8rem; color: #4c5a6d; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status-dot.ok { background: #2f9e6e; }
.status-dot.warn { background: #d99f25; }
.status-dot.off { background: #aeb6c2; }

/* ---------- user bubble ---------- */
.user-bubble {
    background: #e8eef4; border-radius: 14px 14px 3px 14px;
    padding: .68rem .9rem; margin: .35rem 0 1.0rem auto;
    max-width: 40rem; width: fit-content;
}

/* ---------- answer block ---------- */
.answer-shell { margin-bottom: .4rem; }

/* ---------- evidence summary chips ---------- */
.evidence-summary { display: flex; flex-wrap: wrap; gap: .45rem; margin: .25rem 0 .6rem; }
.evidence-chip {
    border: 1px solid rgba(120, 130, 145, .28); border-radius: 999px;
    padding: .12rem .55rem; font-size: .72rem; letter-spacing: .04em;
    color: #45657a; background: #f4f7fa;
}

/* ---------- evidence cards ---------- */
.evidence-card {
    border: 1px solid rgba(120, 130, 145, .22); border-radius: 9px;
    padding: .55rem .75rem; margin: .45rem 0;
    background: #fbfcfe;
}
.evidence-card-head { display: flex; align-items: baseline; gap: .55rem; }
.evidence-id { font-weight: 650; font-size: .82rem; color: #1d2a36; }
.evidence-kind { font-size: .68rem; letter-spacing: .1em; color: #50718b; }
.evidence-meta { font-size: .78rem; color: #69768a; margin: .15rem 0 .3rem; overflow-wrap: anywhere; }
.evidence-snippet {
    font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
    font-size: .78rem; color: #2c3f4f; background: #f4f6f9;
    border-left: 2px solid rgba(120,130,145,.35);
    padding: .45rem .6rem; margin: .25rem 0 .1rem;
    white-space: pre-wrap; overflow-wrap: anywhere;
}

/* ---------- activity timeline ---------- */
.activity-line { font-size: .86rem; line-height: 1.45; margin: .1rem 0; }
.activity-icon { display: inline-block; width: 1.1rem; }
.activity-running { color: #2b759e; }
.activity-complete { color: #2f7e5b; }
.activity-blocked { color: #b1771c; }
.activity-error { color: #b23b3b; }
.activity-muted { color: #69768a; }

/* ---------- empty state ---------- */
.empty-state { text-align: center; padding: 9vh 1rem 3vh; color: #536170; }
.empty-state h2 { color: #1d2a36; font-weight: 650; }
.empty-state .empty-sub { font-size: .88rem; }
.starter-grid { display: flex; flex-direction: column; gap: .55rem; max-width: 34rem; margin: 2.5rem auto 0; text-align: left; }
.starter-card {
    border: 1px solid rgba(120,130,145,.28); border-radius: 9px;
    padding: .7rem .95rem; font-size: .88rem; color: #31404f;
    background: #fbfcfe;
}

/* ---------- status banner variants ---------- */
.banner-refused { border-left: 3px solid #d99f25; }
.banner-failed { border-left: 3px solid #b23b3b; }
.banner-deferred { border-left: 3px solid #2b759e; }

[data-testid="stChatInput"] { padding-bottom: 1rem; }
</style>
"""


def apply_theme() -> None:
    """Inject the shared CSS into the current page. Idempotent per run."""

    st.markdown(CSS, unsafe_allow_html=True)


__all__ = ["CSS", "apply_theme"]
