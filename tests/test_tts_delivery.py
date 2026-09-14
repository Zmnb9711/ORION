"""Real local gRPC wire, no cloud, microphone, DCS or SRS."""
import asyncio

import grpc
import pytest

from orion.protected_streaming_tts import ProtectedStreamingTts, p, safe_rpc_failure, GRPC_RECEIVE_LIMIT


@pytest.mark.parametrize('mode', ['normal', 'cumulative', 'old_limit_shape', 'oversized', 'remote_error', 'partial'])
def test_local_grpc_distinguishes_message_limit_and_recovers(monkeypatch, mode):
    async def run():
        seen, observed = [], []
        calls = 0

        async def synthesize(requests, context):
            nonlocal calls
            calls += 1
            req = [r async for r in requests]
            seen.append(req[1].synthesis_input.text)
            if calls == 1 and mode == 'remote_error':
                await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'SECRET provider body and authorization')
            sizes = [600000, 600000] if mode == 'cumulative' else [GRPC_RECEIVE_LIMIT+100] if mode == 'oversized' and calls == 1 else [1267600] if mode == 'old_limit_shape' else [9600]
            for size in sizes:
                yield p.StreamSynthesisResponse(audio_chunk=p.AudioChunk(data=bytes(size)))
            if calls == 1 and mode == 'partial':
                await context.abort(grpc.StatusCode.INTERNAL, 'SECRET provider body')

        server = grpc.aio.server()
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('speechkit.tts.v3.Synthesizer', {
            'StreamSynthesis': grpc.stream_stream_rpc_method_handler(synthesize,
                request_deserializer=p.StreamSynthesisRequest.FromString,
                response_serializer=p.StreamSynthesisResponse.SerializeToString)}),))
        port = server.add_insecure_port('127.0.0.1:0')
        await server.start()
        insecure = grpc.aio.insecure_channel
        monkeypatch.setattr(grpc.aio, 'secure_channel', lambda target, credentials, options: insecure(f'127.0.0.1:{port}', options=options))
        tts = ProtectedStreamingTts('fixture-no-secret')
        tts.observe_diagnostic = lambda e, **f: observed.append((e, f))
        text = '  Exact finalized text.\n'
        try:
            chunks = []
            try:
                async for chunk in tts.stream(text): chunks.append(chunk)
            except RuntimeError:
                assert mode in {'oversized', 'remote_error', 'partial'}
            else:
                assert mode in {'normal', 'cumulative', 'old_limit_shape'}
            if mode == 'oversized':
                failure = next(f for e, f in observed if e == 'tts_rpc_failed')
                assert failure['failure_category'] == 'TTS_GRPC_CLIENT_LIMIT'
                assert failure['rejected_message_bytes'] > GRPC_RECEIVE_LIMIT and not chunks
            if mode == 'cumulative': assert sum(map(len, chunks)) == 1200000
            if mode == 'partial': assert sum(map(len, chunks)) == 9600
            if mode == 'remote_error':
                failure = next(f for e, f in observed if e == 'tts_rpc_failed')
                assert failure['rpc_origin'] == 'UNDETERMINED' and not chunks
            assert 'SECRET' not in repr(observed)
            assert tts._call is None
            assert [chunk async for chunk in tts.stream(text)]
            assert calls == 2 and seen == [text, text]  # Independent later turn, not a retry.
            assert tts._call is None
        finally:
            await tts.aclose()
            await server.stop(None)
    asyncio.run(run())


def test_rpc_details_are_closed_grammar_not_provider_body_logging():
    for text in ('Api-Key secret', 'Received message larger than max (9999999 vs. 1048576) SECRET', None):
        assert safe_rpc_failure('RESOURCE_EXHAUSTED', text)['rpc_origin'] == 'UNDETERMINED'
    assert safe_rpc_failure('RESOURCE_EXHAUSTED', 'CLIENT: Received message larger than max (1200010 vs. 1048576)')['rejected_message_bytes'] == 1200010


@pytest.mark.parametrize('mode', ['normal', 'before_pcm', 'partial_producer', 'consumer', 'backpressure',
                                  'reject', 'cancel_before', 'cancel_after', 'deadline'])
def test_real_presentation_router_bounded_stream_failure_and_next_turn(mode):
    import threading
    import time
    from types import SimpleNamespace
    from uuid import uuid4
    from orion.protected_streaming_presentation import StreamingProtectedPresentation
    from orion.radio_contracts import RadioReadiness, RadioAdapterTxResult, RadioAdapterOutcome
    from orion.radio_router import RadioRouter
    from test_full_voice import StreamingFakeRadio, NOW
    from fallback_protected_presentation_probe import protected_probe_cases
    from orion.radio_contracts import RadioContext, RadioEntityRef, RadioModulation
    from orion.protected_presentation import tx_correlation

    async def run():
        events, streams, workers = [], [], []
        first = threading.Event()
        active_mode = mode
        class Adapter(StreamingFakeRadio):
            def transmit(self, request):
                self.transmit_calls.append(request)
                stream = request.audio.stream
                streams.append(stream)
                workers.append(threading.current_thread())
                try:
                    stream.wait_prebuffer()
                    while True:
                        data, end = stream.read(3528)
                        if data: first.set()
                        if active_mode == 'consumer' and data:
                            stream.abort('stream_tx_failed')
                            raise RuntimeError('fixture_consumer_failure')
                        if active_mode == 'backpressure':
                            # Consumer stalls; producer retains its real two-second bound.
                            while stream.first_abort_code is None: time.sleep(.005)
                            stream.read(3528)
                        if end: break
                        time.sleep(.001)
                    return RadioAdapterTxResult(tx_correlation_id=request.context.tx_correlation_id,
                        outcome=RadioAdapterOutcome.COMPLETED, completed_at=NOW)
                finally:
                    workers.remove(threading.current_thread())

        class Tts:
            def __init__(self): self.calls = 0; self.active = False
            async def stream(self, text):
                self.calls += 1
                self.active = True
                try:
                    if active_mode == 'before_pcm': raise RuntimeError('streaming_tts_empty')
                    if active_mode in {'cancel_before', 'deadline'}: await asyncio.Event().wait()
                    yield bytes(24000)
                    if active_mode in {'partial_producer', 'consumer', 'cancel_after'}:
                        assert await asyncio.to_thread(first.wait, 1)
                    if active_mode == 'partial_producer': raise RuntimeError('streaming_tts_pcm_bound')
                    if active_mode == 'cancel_after': await asyncio.Event().wait()
                    yield bytes(240000 if active_mode == 'backpressure' else 24000)
                finally: self.active = False
            async def aclose(self): pass

        adapter, tts = Adapter(first), Tts()
        router = RadioRouter(default_transport_id='srs')
        router.register_adapter(adapter); router.start()
        presentation = StreamingProtectedPresentation(tts, router)
        presentation.observe_diagnostic = lambda e, **f: events.append((e, f))
        def launch():
            final = protected_probe_cases(uuid4())[0].finalized
            radio = RadioContext(tx_correlation_id=tx_correlation(final.interaction_id),
                source_domain=final.context.domain, interaction_id=final.interaction_id,
                communication_priority=final.priority, radio_entity=RadioEntityRef(entity_id='fixture', operational_callsign='ORION'),
                target_frequency_hz=251000000, modulation=RadioModulation.AM)
            return asyncio.create_task(presentation._run(final, radio, SimpleNamespace(accepted=False, result=None)))
        try:
            if mode == 'reject': adapter.readiness = RadioReadiness.UNAVAILABLE
            if mode == 'deadline': presentation._radio_timeout = .1
            task = launch()
            if mode.startswith('cancel'):
                if mode == 'cancel_after': assert await asyncio.to_thread(first.wait, 1)
                else:
                    while not tts.active: await asyncio.sleep(.001)
                task.cancel()
            outcome = await asyncio.wait_for(task, 4)
            assert outcome.state == ('completed' if mode == 'normal' else 'cancelled' if mode.startswith('cancel') else 'unknown' if mode == 'deadline' else 'failed')
            for _ in range(200):
                if not workers: break
                await asyncio.sleep(.005)
            assert not workers and not tts.active and not presentation._streams
            assert all(not s._buffer for s in streams)
            assert all(f['producer_done'] for e, f in events if e == 'presentation_terminal')
            if mode == 'backpressure':
                assert any(f.get('failure_category') == 'PCM_BACKPRESSURE_FAILURE' for _, f in events)
            prior_calls = tts.calls
            active_mode = 'normal'; adapter.readiness = RadioReadiness.READY
            presentation._radio_timeout = 3
            assert (await asyncio.wait_for(launch(), 4)).state == 'completed'
            assert tts.calls == prior_calls + 1 and not tts.active
            assert len({s.identity for s in streams}) == len(streams)
            assert not any(t.get_name() == 'protected-stream-producer' for t in asyncio.all_tasks() if not t.done())
        finally: assert await presentation.shutdown()
    asyncio.run(run())


def test_historical_collision_guard_first_abort_preserved(tmp_path):
    from orion.bounded_radio_stream import BoundedPcmStream
    from test_full_voice_srs import build
    from test_yandex_srs_live_core import human_packet
    endpoint = build(tmp_path)
    stream = BoundedPcmStream()
    try:
        endpoint._stream = stream
        endpoint.expected_origin = 'fixture-unexpected'
        endpoint._on_radio_datagram(human_packet())
        assert endpoint.stop_event.is_set()
        assert str(endpoint.failure()) == 'srs_collision_or_unexpected_origin'
        assert stream.first_abort_code == 'srs_collision_or_unexpected_origin'
        stream.abort('presentation_terminal')
        assert stream.first_abort_code == 'srs_collision_or_unexpected_origin'
    finally: endpoint.stop()


def test_diagnostics_export_keeps_safe_cause_and_never_provider_prose(tmp_path):
    import json
    import zipfile
    from orion.realtime_test_evidence import RealtimeTestEvidenceRecorder
    recorder = RealtimeTestEvidenceRecorder(tmp_path)
    recorder.record('endpoint_error', error='srs_collision_or_unexpected_origin')
    assert recorder.status().event_count == 0
    recorder.start(provider='yandex', transport='srs')
    from orion.protected_streaming_presentation import stream_failure
    recorder.record_conversation_slice('delivery_diagnostic', realtime_session_id='fixture',
        diagnostic_stage='tts_stream_abort', **stream_failure('srs_collision_or_unexpected_origin', 'PCM_PRODUCER'))
    recorder.record_conversation_slice('delivery_diagnostic', realtime_session_id='fixture',
        diagnostic_stage='tts_stream_abort', **stream_failure('SECRET arbitrary error', 'PCM_PRODUCER'))
    recorder.record_conversation_slice('delivery_diagnostic', diagnostic_stage='tts_rpc_failed', realtime_session_id='fixture', turn_id='turn-1',
        tts_request_id='rpc-1', rpc_code='RESOURCE_EXHAUSTED',
        **safe_rpc_failure('RESOURCE_EXHAUSTED', 'Received message larger than max (1267589 vs 1048576)'))
    recorder.record_conversation_slice('delivery_diagnostic', diagnostic_stage='tts_rpc_failed', realtime_session_id='fixture',
        **safe_rpc_failure('INTERNAL', 'SECRET provider body'))
    with zipfile.ZipFile(recorder.stop_and_export()) as archive:
        raw = archive.read('events.jsonl').decode()
    assert 'SECRET' not in raw
    rows = list(map(json.loads, raw.splitlines()))
    assert rows[0]['safe_error_code'] == 'srs_collision_or_unexpected_origin'
    assert rows[1]['safe_error_code'] == 'unrecognized_local_error'
    assert rows[2]['failure_category'] == 'TTS_GRPC_CLIENT_LIMIT'
    assert rows[2]['rejected_message_bytes'] == 1267589


def test_step3_exact_runtime_scope_and_request_identity():
    import subprocess
    from pathlib import Path
    from orion.protected_streaming_tts import protected_stream_requests
    from general_ingress_scope import verify_general_scope
    root = Path(__file__).resolve().parents[1]
    parent = '152a2f22c281fc31ab00daf99f4e171af88c05f9'
    paths = {'orion/protected_streaming_tts.py', 'orion/protected_streaming_presentation.py',
             'orion/bounded_radio_stream.py', 'orion/realtime_test_evidence.py'}
    changed = set(subprocess.check_output(['git', 'diff', parent, '--name-only', '--',
        'orion', 'packaging', 'dcs-export'], cwd=root).decode().splitlines())
    assert changed == paths
    verify_general_scope()
    text = '  Finalized exact text.\n'
    requests = protected_stream_requests(text)
    assert requests[1].synthesis_input.text == text
    assert requests[0].options.voice == 'john' and requests[0].options.speed == 1.0
    assert requests[0].options.output_audio_spec.raw_audio.sample_rate_hertz == 48000
    assert requests[2].HasField('force_synthesis')
