# Product direction — natural AI language with Core-authoritative DCS

Decision date: 2026-09-10, Europe/Moscow. Status: product intent clarified; architectural design/implementation deferred.
Canonical results and evidence: [end-of-day checkpoint](history/2026-09-10-end-of-day-checkpoint.md).

ORION's target is natural/free AI language understanding with access to permitted DCS data/actions, not a growing library of predetermined voice templates. AI interprets the natural request. If facts are needed, it requests only allowed Core/ToolGateway facts; Core remains the source of truth and action authority. Planner owns reasoning; Conversation owns natural language. No model-generated value becomes a DCS fact merely by being spoken fluently.

At d3245292c176d6dc51b2a9adcb71b2e238e0b234, genuine generated Conversation and Core DCS fact routes work separately. Conversation's admitted input remains bounded; it has no DCS/WorldModel/ToolGateway access. General natural understanding of arbitrary DCS-data requests plus retrieval of their required facts is not implemented. Existing Planner/tool infrastructure does not mean this layer is wired before ordinary speech.

The next architectural stage is to design the missing AI interpretation/tool-mediated layer. This direction preserves the existing authority boundary; it is not authorization to dump telemetry into Conversation, create universal fallback, transfer action authority, or patch an unlimited list of phrases tonight.

A later design should specify intent interpretation, allowed capability selection, Core policy enforcement, exact fact/result binding, freshness/unknown/unavailable responses, mixed social/factual requests, Planner ownership, and any action confirmation/lifecycle requirements. Acceptance should cover natural paraphrases and subset intent without adding unrequested facts, plus the established Conversation/Aircraft/Hybrid/golden ownship routes and negative cases. These are design questions and recommended criteria, not newly implemented contracts.

Recommended process follow-up: build a Capability Preservation Matrix/gate through the actual production host, keeping historical FIELD evidence, offline reachability, source invariance and future coverage expectations distinct. The earlier audit's matrix and 12 scenarios do not constitute an installed gate. Silent source labels/internal provenance remain standing policy. Latency optimization follows architecture/correctness.
