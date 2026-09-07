# 18:00 historical fallback — migration manifest

## Current checkpoint — 2026-09-07

The migration below was committed as `3f364bdfb05d4c2a0141f75708032ec7a26e768b`.
The installed, physically validated source is its direct child
`333ca5e481c89b8294e0f491fbd2d2e6d6e87319`: only the separately authorized
STT-to-Core terminal observation plus tests. That addition records exact FINAL
text only during an explicit Test Session; existing recorder START/STOP/export,
Launcher/Core/SRS lifecycle and golden voice components remain unchanged.

The installed runtime completed turn `d9b31e5c-9853-4c07-994a-297490ef32d3`,
FINAL `какой мой текущий курс и координаты`, and 385 response TX frames;
the user confirmed the response was heard clearly. This supersedes the historical
"no build/installation yet" status at the end of the original migration record.
Full source/build/evidence identity, limitations and excluded work are in the
[canonical recovered working checkpoint](recovered-working-checkpoint.md).
The record below describes the original migration, not a new implementation task.

Baseline: `a955d7c39f20c020e15de6bc2be272755928cc98`.
Tree: `7c010efadc2a8c0b6b892b49354a4019e4fdb3b2`.
Cutoff: 2026-09-06 18:00 Europe/Moscow (15:00 UTC).
Recovery branch/HEAD reflog resolves this exact commit at the cutoff. Branch
creation at 2026-09-04 20:47 and next commit at 2026-09-06 20:50 bracket it.
Git proves committed HEAD, not any unsaved/uncommitted historical files.
ef7f047 is dated 2026-09-07 16:26 and is NOT the baseline.

Today's work is retained on recovery/a955d7c-radio-validated through
`2c9d20f4ca406ef7039e4672252e8eb370ac4dc9`; existing untracked forensic/generated
artifacts and build directories remain in place. This separate worktree starts
directly from the immutable baseline commit, not a reverse reconstruction.

## Implemented minimal ports

All existing component ports come verbatim from golden
`57a563a067c980c3ff8057172aa6f5fefb33a5b0`, never today's integration.
Changes to existing radio modules are the golden opt-in physical-turn/stream
dependencies listed below, not new readiness rules or changes to legacy defaults.

### orion/full_voice_capture.py

This change is required because without it the already field-validated full-voice path cannot execute: PhysicalRadioTurn converts UDP7082 start/end and received PCM into one bounded physical turn.

### orion/srs_tx_state.py

This change is required because without it the already field-validated full-voice path cannot execute: SrsTxStateListener/parse_combined_radio_state supply the physical PTT edges consumed by PhysicalRadioTurn.

### orion/full_voice_srs.py

This change is required because without it the already field-validated full-voice path cannot execute: FullVoiceSrsEndpoint connects that physical-turn owner to native SRS RX and streaming TX.

### orion/full_voice_stt.py

This change is required because without it the already field-validated full-voice path cannot execute: NativeSpeechKitTurns and FinalizedUserUtterance enforce the validated FINAL/External-EOU barrier.

### orion/speechkit_v3_stt_transport.py

This change is required because without it the already field-validated full-voice path cannot execute: GrpcSpeechKitStreamingPort supplies the native v3 options/audio/EOU/event protocol used by NativeSpeechKitTurns.

### orion/yandex_speechkit_v3_proto/__init__.py; stt_pb2.py; stt_pb2.pyi; tts_pb2.py; PROVENANCE.md

This change is required because without it the already field-validated full-voice path cannot execute: the STT/TTS transports import these pinned protocol message classes; provenance accompanies the generated definitions.

### orion/full_voice_core.py

This change is required because without it the already field-validated full-voice path cannot execute: FullVoiceCore dispatches the finalized utterance through IA-6, typed ownship semantics and protected composition.

### orion/interaction_router.py

This change is required because without it the already field-validated full-voice path cannot execute: the golden opt-in bounded_ownship_gateway route executes the authoritative ownship ToolGateway call; baseline has no such route.

### orion/ownship_report.py

This change is required because without it the already field-validated full-voice path cannot execute: ownship_semantics_from_tool_result/map_ownship_report select and validate exactly heading/latitude/longitude before rendering.

### orion/ownship_phraseology.py

This change is required because without it the already field-validated full-voice path cannot execute: OwnshipReportRuleset renders that typed report; the generic baseline renderer does not exist.

### orion/phraseology_renderer.py

This change is required because without it the already field-validated full-voice path cannot execute: PhraseologyRenderer is the Stage 7A typed-to-protected-fragment boundary called by FullVoiceCore.

### orion/communication_contracts.py

This change is required because without it the already field-validated full-voice path cannot execute: FinalizedCommunicationText and composition bounds are required by Stage 7B and protected presentation.

### orion/response_composer.py

This change is required because without it the already field-validated full-voice path cannot execute: ResponseComposer creates the immutable finalized text consumed by protected presentation.

### orion/protected_presentation.py

This change is required because without it the already field-validated full-voice path cannot execute: StreamingProtectedPresentation inherits the validated 7C validation, operation ownership, deduplication and shutdown implementation.

### orion/speechkit_tts_adapter.py

This change is required because without it the already field-validated full-voice path cannot execute: protected_presentation imports its protected TTS types/errors/PCM contracts; this is a golden module dependency, not activation of legacy v1 synthesis.

### orion/protected_streaming_presentation.py

This change is required because without it the already field-validated full-voice path cannot execute: StreamingProtectedPresentation passes exact finalized text and streaming PCM through the existing RadioRouter.

### orion/protected_streaming_tts.py

This change is required because without it the already field-validated full-voice path cannot execute: ProtectedStreamingTts produces direct john LINEAR16 PCM from exact protected text.

### orion/bounded_radio_stream.py

This change is required because without it the already field-validated full-voice path cannot execute: BoundedPcmStream is the buffer shared by protected streaming presentation and the SRS endpoint.

### orion/radio_contracts.py

This change is required because without it the already field-validated full-voice path cannot execute: StreamingPcmAudio/STREAMING_PCM represent the golden stream; baseline requests accept finalized PCM only.

### orion/radio_router.py

This change is required because without it the already field-validated full-voice path cannot execute: the golden capability/signature branches admit and correlate StreamingPcmAudio without reading nonexistent finalized .pcm.

### orion/srs_radio_adapter.py

This change is required because without it the already field-validated full-voice path cannot execute: the golden opt-in transmit_srs_stream branch dispatches streaming requests; the baseline only calls transmit_srs_pcm.

### orion/srs_transmission.py

This change is required because without it the already field-validated full-voice path cannot execute: expire_on_quiescence=False/complete_active preserve a physical turn across silence; streaming=True allows the validated TX generator. Existing caller defaults stay unchanged.

### pyproject.toml

This change is required because without it the already field-validated full-voice path cannot execute: the native v3 transport requires the golden grpcio/protobuf optional dependency group.

### orion/full_voice_service.py (new minimal handoff)

This change is required because without it the already field-validated full-voice path cannot execute: the existing YandexSrsLiveService owner needs an _run implementation executing the golden component sequence against the already-owned Core WorldModel. Inherit its exact start/status/stop, thread ownership and timeout; do not import today's worker.

### orion/realtime_live_core.py (three import substitutions only)

This change is required because without it the already field-validated full-voice path cannot execute: the existing Yandex/SRS adapter must address the full-voice service for start/status/stop; otherwise START LIVE invokes the legacy Realtime pipeline.

## Deliberately excluded

Today's full_voice_runtime.py and full_voice_evidence.py; voice_latency_profile.py
and all post-golden instrumentation; Launcher UI/profile/evidence controls;
realtime_test_evidence_api and realtime_tool_api changes; app lifespan shutdown
hooks; core_process timeout changes; coordinator/controller stopping semantics;
new packaging/build identity/smoke endpoints; EAM/port/configuration changes;
ownship context refactor; Realtime STT investigations and Qwen experiments.
No field CLI, second RecoveryLiveWorld owner or live probe is deployed.
At migration commit 3f364bdf, old Test Evidence, diagnostics, UI, Core lifecycle
and SRS process control remained literal baseline files. Commit 333ca5e adds only
the explicitly approved boundary recorder described above. Golden scalar timing fields remain inside unchanged
components; no profiling facility or RX/TX WAV integration is added.

## Verified exact Launcher/Core/SRS lifecycle diff

Only three imports in _YandexSrsLiveAdapter point to the new full-voice service
under the existing local alias. No change to adapter methods, request selection,
normalization, coordinator state rules, STOP release, session controller,
Core shutdown or SRS process lifecycle. New service inherits historical
YandexSrsLiveService.start/status/stop directly and replaces _run only.
Normal START LIVE continues using the existing Yandex + SRS selection/config.
The handoff borrows Core's actual world_model and existing credentials/config;
no second telemetry ingress or world is created.

The three substitutions are in realtime_live_core.py:start_live/live_status/stop_live:
the existing local name `yandex_srs_live` now refers to `full_voice_service`.
No class/method body changes other than these imports occur in that file.
FullVoiceService adds only _run/_voice; __init__/start/status/_set/stop are the
same inherited method objects as baseline YandexSrsLiveService. Its STOP timeout
is the old 6 seconds and Core completion wait remains 3 seconds. No `stopping`
state, app shutdown hook, timeout extension or alternate owner was added.
SRS transport/protocol/codec/resampler and process-control files remain exact
baseline. The only shared radio diffs are the explicitly listed golden
opt-in streaming/physical-turn dependencies; legacy defaults are unchanged.

The field CLI's second WorldModel ingress, temporary report writer, CLI
turn-count/time-window termination and secure-store loading are not deployed:
the unchanged old service controls session lifetime and supplies its existing
request/config/credentials. The golden component sequence and original
RadioContext/freshness calculation are copied into _voice without today's
context refactor, readiness gates or evidence machinery.

## Original migration-time offline validation — before build/field validation

- 257 component/semantic/lifecycle/baseline tests PASS.
- 3 differential oracle tests PASS, comprising 168 host-turn executions:
  exact golden field host versus fallback old-owner service, two PCM sources
  (fixture and saved RX), two coalition metadata values, full/missing/lost
  peer metadata, seven supported/unsupported/format-boundary queries.
- Compare one finalized utterance/EOU, exact PCM chunks, request protobufs,
  typed selected values, finalized/TTS text, TX admission/frequency/entity,
  initialization/cleanup order and endpoint release. Extra telemetry cannot
  leak to speech. No actual ASR transcription of the saved WAV is claimed;
  FINAL is an explicit fixture, matched to the historical successful hashes.
- Source equality tests prove each ported production component and protobuf
  file equals golden (normalizing checkout line endings only), and old
  Launcher/Core lifecycle files equal a955d7c.
- Ruff and scoped Pyright for the new service pass. One existing
  Starlette/httpx deprecation warning. No PTT/provider/audio-device calls.

Golden test probe helpers live under tests/fallback_* only; they are not
deployed production features. Today's replay harness is reused only as a
test oracle, adjusted to execute the inherited old owner, with network
connection/channel/send calls forbidden. No today's production modules enter it.
An initial test run found a helper path still targeting orion/; this test-only
path was corrected to tests/, then the complete component suite passed.

At migration completion, no broader Launcher/Core/SRS lifecycle change proved
necessary and no fallback build/installation had yet occurred. Build-07 was not
the new baseline. That historical status is superseded by the installed fallback
physical PASS and freeze at the top of this document, not by build-07.
