# Support Search demo project

This small project is a static investigation fixture for the Engineering Agent.
The default result limit is 4. Set SUPPORT_RESULT_LIMIT to override it.
Allowed result limits are integers from 1 through 20, inclusive.
search_help forwards the configured limit to the supplied retriever.

The preparation command deliberately changes the default from 4 to 6 while
leaving this document and the default-value test unchanged. The Agent should
read the real sources, identify the conflict, and suggest tests without running
them. This fixture is a demonstration, not an unseen evaluation dataset.
