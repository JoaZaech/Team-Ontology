# Paper architecture figures

These figures document the current implementation and the proposed hybrid
architecture without presenting proposed components as already operational.

For the consolidated deployable-service topology and migration plan, see
[the microservice architecture](../MICROSERVICE_ARCHITECTURE.md). The figures
in this directory describe research and evidence flow; they are not the runtime
deployment diagram.

## Component status

| Component | Status | Role |
| --- | --- | --- |
| Deterministic rule engine (`guardian.py`, `rulebook.py`) | Implemented and tested | Enforces mandate/card state, spend limits, basket constraints, merchant familiarity, and attempt velocity. |
| Historical merchant counter (`MerchantHistory`) | Implemented and tested | Supplies approved card–merchant counts from the CSV history. This is a small in-memory context lookup, not a deployed knowledge graph. |
| Precomputed knowledge graph / online projection | Proposed | Materializes card–merchant, card–device, card–category, recency, and rolling-activity evidence with provenance. |
| Gaussian anomaly model | Proposed | Estimates how unusual continuous behaviour is relative to a reference profile; it should normally influence `step_up`, not relax or override hard rules. |
| Bayesian evidence-fusion model | Proposed | Combines discrete graph evidence and Gaussian likelihood into a calibrated uncertainty posterior. |
| Hierarchical decision policy | Proposed | Declines hard violations, approves rule-compliant low-uncertainty requests, and escalates ambiguous or elevated-risk requests. |

The Gaussian and Bayesian components are complementary in these figures:
the Gaussian model produces a behavioural likelihood, while the Bayesian
network combines that likelihood with discrete evidence. They are not currently
implemented in the repository.

## Figure set

1. `figure-1-overall-architecture` — complete hybrid system.
2. `figure-2-offline-knowledge-flow` — historical knowledge construction.
3. `figure-3-online-decision-flow` — real-time authorization path.
4. `figure-4-step-up-feedback-flow` — customer resolution and feedback.
5. `figure-5-explanation-provenance-flow` — explanation and audit evidence.

Each figure is generated in SVG and high-resolution PNG formats. SVG is the
publication master and can be exported to PDF by the paper-authoring toolchain. Solid borders indicate
implemented components; dashed borders indicate proposed components.

## Regeneration

Run `render_figures.mjs` with Node.js. It uses the bundled Viz.js Graphviz
renderer for SVG and Sharp for PNG.
Set `CODEX_NODE_MODULES` when the bundled dependency directory differs from the
default encoded in the script.
