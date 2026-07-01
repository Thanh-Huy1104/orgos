"""orgos worked-example: a self-organizing agile engineering team.

Modules:
    envelopes  - Seven typed HandoffEnvelope subclasses for the sprint chain.
    sprint     - run_sprint() / run_nightly_sprint() entrypoints.
    intake     - Backlog ranker (GitHub issues -> ranked candidates).
    rubric     - QA validator's grading rubric.
    dora       - DORA metric computations over PMStore.
    retro      - Retro Agent helpers.
    attribution - Per-role marginal-contribution scoring (Hook A).
    topology   - Mutation proposal trigger rules (Hook A).
    replay     - Counterfactual sprint replay (Hook B).
"""
