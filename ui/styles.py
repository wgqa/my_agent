"""Central Streamlit theme for the Engineering Agent product shell.

R1 pass: suppress the default-Streamlit look as much as one CSS file can.
The scheme is a compact developer-tool surface: narrow page header, contained
main column, quiet sidebar, small mono evidence blocks, and color + text
status chips that never depend on color alone.
"""

from __future__ import annotations

import streamlit as st


CSS = """
<style>
/* =============================================================
   Page frame: tighter top, narrower main column, darker sidebar
   ============================================================= */
.block-container { padding-top: 1.4rem; max-width: 62rem; }
[data-testid="stSidebar"] { border-right: 1px solid rgba(120, 130, 145, .18); background: #fafbfc; }
[data-testid="stSidebar"] .block-container { padding-top: 1.2rem; max-width: 17rem; }

/* Shrink the auto page title; the in-page `st.title` is the only h1 we need */
h1 { font-size: 1.55rem !important; font-weight: 650 !important; letter-spacing: -0.01em !important; color: #16222c !important; margin-bottom: 0 !important; }

/* =============================================================
   Sidebar product mark and section labels
   ============================================================= */
.product-mark-kicker { font-size: .6rem; letter-spacing: .15em; text-transform: uppercase; color: #97a2b1; }
.product-mark-title { font-size: 1.02rem; font-weight: 700; letter-spacing: .01em; margin: .06rem 0 .06rem; color: #16222c; }
.product-mark-sub { font-size: .72rem; color: #6d7b8d; margin-bottom: .65rem; }
.sidebar-section { font-size: .6rem; letter-spacing: .14em; text-transform: uppercase; color: #97a2b1; margin: .85rem 0 .25rem; }
.sidebar-spacer { min-height: 4vh; }

/* Conversation rows: snug two-cell grid, delete is a quiet icon */
.conversation-grid { display: grid; grid-template-columns: 1fr auto; align-items: center; gap: .2rem; margin: .05rem 0; }
.conversation-label { font-size: .82rem; color: #1d2a36; padding: .4rem .55rem; border-radius: 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conversation-label.active { background: rgba(70, 90, 110, .10); font-weight: 550; }
.conversation-delete { font-size: .8rem; color: #a7b2c1; border: none; background: transparent; padding: .15rem .3rem; cursor: pointer; border-radius: 4px; }
.conversation-delete:hover { color: #4a5869; background: rgba(70, 90, 110, .08); }

/* =============================================================
   Workspace rows: single-line with small color dot
   ============================================================= */
.workspace-row { display: flex; align-items: center; gap: .4rem; font-size: .74rem; color: #4c5a6d; margin: .06rem 0; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
.status-dot.ok { background: #2f9e6e; }
.status-dot.warn { background: #d99f25; }
.status-dot.off { background: #aeb6c2; }

/* =============================================================
   Hero (smaller), starter prompt cards
   ============================================================= */
.hero-sub { color: #5a6b7e; font-size: .84rem; margin: .08rem 0 0; }
.capability-chips { display: flex; gap: .4rem; margin: .6rem 0 .85rem; }
.capability-chip { font-size: .62rem; letter-spacing: .1em; color: #45657a; background: #f0f4f7; border-radius: 999px; padding: .22rem .55rem; border: 1px solid #e2e8ee; }
.empty-sub { color: #5a6b7e; font-size: .86rem; margin: .2rem 0 0; }
.empty-heading { color: #1d2a36; font-weight: 600; font-size: 1.06rem; margin: .05rem 0 .3rem; }
.starter-grid-header { font-size: .72rem; letter-spacing: .1em; text-transform: uppercase; color: #7c8794; margin: 1.1rem 0 .4rem; }

/* =============================================================
   Answer: lightweight "Agent answer" label + rule
   ============================================================= */
.answer-label { font-size: .64rem; letter-spacing: .12em; text-transform: uppercase; color: #7c8794; margin: 0 0 .28rem; }
.answer-rule { height: 1px; background: rgba(120,130,145,.18); margin: 0 0 .55rem; }

/* =============================================================
   User bubble: narrower, smoother corners, neutral color
   ============================================================= */
.user-bubble {
    background: #eef2f5; border-radius: 10px 10px 2px 10px;
    padding: .5rem .75rem; margin: .25rem 0 .85rem auto;
    max-width: 34rem; width: fit-content; font-size: .88rem; color: #1d2a36;
}

/* =============================================================
   Evidence summary chips + expandable cards (snug)
   ============================================================= */
.evidence-summary { display: flex; flex-wrap: wrap; gap: .35rem; margin: .15rem 0 .4rem; }
.evidence-chip {
    border: 1px solid rgba(120, 130, 145, .24); border-radius: 999px;
    padding: .1rem .48rem; font-size: .68rem; letter-spacing: .04em;
    color: #45657a; background: #f4f7fa;
}
.evidence-card {
    border: 1px solid rgba(120, 130, 145, .2); border-radius: 7px;
    padding: .5rem .65rem; margin: .3rem 0; background: #fbfcfe;
}
.evidence-card-head { display: flex; align-items: baseline; gap: .45rem; }
.evidence-id { font-weight: 650; font-size: .76rem; color: #16222c; }
.evidence-kind { font-size: .6rem; letter-spacing: .12em; color: #50718b; }
.evidence-meta { font-size: .72rem; color: #6d7b8d; margin: .1rem 0 .18rem; overflow-wrap: anywhere; }
.evidence-snippet {
    font-family: ui-monospace, "Cascadia Mono", Consolas, monospace;
    font-size: .72rem; color: #2c3f4f; background: #f4f6f9;
    border-left: 2px solid rgba(120,130,145,.3);
    padding: .35rem .5rem; margin: .2rem 0 .05rem;
    overflow-wrap: anywhere; white-space: pre-wrap;
    max-height: 14rem; overflow-y: auto;
}

/* =============================================================
   Activity timeline: smaller lines, padded icons
   ============================================================= */
.activity-line { font-size: .78rem; line-height: 1.35; margin: .06rem 0; color: #2b3a4a; }
.activity-icon { display: inline-block; width: .95rem; }
.activity-running { color: #2b759e; }
.activity-complete { color: #2f7e5b; }
.activity-blocked { color: #b1771c; }
.activity-error { color: #b23b3b; }
.activity-muted { color: #8fa0b2; }

/* =============================================================
   Banner variants: small colored left rule
   ============================================================= */
.banner-refused { border-left: 3px solid #d99f25; }
.banner-failed { border-left: 3px solid #b23b3b; }
.banner-deferred { border-left: 3px solid #2b759e; }

/* =============================================================
   Execution section: compressed one-line summary
   ============================================================= */
.execution-summary-line { font-size: .78rem; color: #3a4a5a; margin: .1rem 0 .4rem; }
.execution-summary-line .sep { color: #a7b2c1; margin: 0 .3rem; }

[data-testid="stChatInput"] { padding-bottom: .6rem; max-width: 62rem; margin: 0 auto; }
</style>
"""


def apply_theme() -> None:
    """Inject the shared CSS into the current page. Idempotent per run."""

    st.markdown(CSS, unsafe_allow_html=True)


__all__ = ["CSS", "apply_theme"]
