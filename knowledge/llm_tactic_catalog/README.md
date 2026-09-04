# LLM Tactic Catalog

Each JSON file is a natural-language tactic card for the model.

After a tactic is selected, its card stays active for the whole game. The model receives the current observation, the complete tactic card, and the currently available action cards. In one response, it selects the matching phase and emits concrete actions.

Each card has four top-level fields:

- `id`: stable, machine-readable tactic identifier.
- `concept`: one-sentence tactical idea.
- `rules`: global rules and phase priority.
- `phases`: a list of `{id, enter_when, goal, guidance}` objects.

The model returns the tagged Function DSL documented in the prompt output contract: one phase and zero to six action calls.

The tactic card is not an action table and does not directly execute a build-order runner. The model combines its guidance with the current action surface, and validated actions are registered as Ares behaviors.
