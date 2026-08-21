# Chat-first Agent UI

A chat product needs three information layers with different visual weight:

- **Answer** is the task outcome and should be visible immediately.
- **Evidence** supports trust and can stay available without competing with the answer.
- **Execution trace** explains how the system worked, so it belongs behind an explicit details control.

Keeping those layers separate lets a direct answer remain quiet while preserving the diagnostics needed for demos, interviews, and incident investigation. Session-local conversations are enough for the first version: each conversation owns its mode and messages, so switching conversations cannot mix Basic, Agentic, and Tool Agent histories.
