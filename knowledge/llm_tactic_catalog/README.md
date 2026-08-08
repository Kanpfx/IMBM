# LLM Tactic Catalog

Each JSON file is a natural-language tactic card for BM.

After a tactic is selected, its card stays active for the whole game. BM receives the current observation, the complete card, and the same model-facing action cards used by IM. It selects the matching phase and gives IM concrete phase guidance as current instructions.

Each card has four top-level fields:

- `id`: stable, machine-readable tactic identifier.
- `concept`: one-sentence tactical idea.
- `rules`: global rules and phase priority.
- `phases`: a list of `{id, enter_when, goal, guidance}` objects.

BM returns `{"phase":"<phase id>","guidance":["..."]}`. The prompt requests 1-3 guidance items, while runtime validation only requires a valid phase and a non-empty string list.

The tactic card itself is not an action table and does not directly execute a build-order runner. IM converts BM guidance into valid Ares actions.
