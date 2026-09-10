# ORION assistant workflow

## Mandatory architecture pre-flight

Before any ORION architecture, routing, conversation, interpreter, planner,
capability exposure, Core/ToolGateway or voice-host integration change, read
[the canonical Natural-Language architecture contract](docs/architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md),
then [Project Memory](docs/ORION_PROJECT_MEMORY.md) and its latest recovery history.

Cite `docs/architecture/ORION_NATURAL_LANGUAGE_ARCHITECTURE_CONTRACT.md` and
`ORION_NATURAL_LANGUAGE_FIRST_CONTRACT_V1` before editing. State compliance with
each relevant numbered invariant and identify potential conflicts. Sections
17–19 require STOP before implementation on conflict and explicit user approval
for architecture deviations. Do not narrow open user language into mandatory
phrases or silently supersede this contract. Historical task-specific Guard OFF
notes do not waive this pre-flight. Keep the contract canonical; do not duplicate
its policy here. This file adds the missing startup reference on the recovery
line and does not import unrelated branch policies.
