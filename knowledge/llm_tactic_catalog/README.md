# LLM Tactic Catalog

Each JSON file is a natural-language tactic card for BM.

After a tactic is selected, its card stays active for the whole game. BM reads the current observation, finds the matching phase, and gives IM the phase guidance as current instructions.

Each card has four top-level fields:

- `id`: stable, machine-readable tactic identifier.
- `concept`: one-sentence tactical idea.
- `rules`: global rules and phase priority.
- `phases`: a list of `{id, enter_when, guidance}` objects.

The card is not an action table and does not directly execute a build-order runner. IM converts BM guidance into valid Ares actions.
