import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import protocol_probe as p


class ProbeTests(unittest.TestCase):
    def test_exact_capability_types(self):
        for value in (None,[],["text"],["audio"],["text","audio"],"text",{"unexpected":[]},False,42):
            with self.subTest(value=value):
                field=p.capability({"session":{"output_modalities":value}},p.Safe())["fields"]["output_modalities"]
                self.assertTrue(field["present"])
                self.assertEqual(field["type"],p.json_type(value))
                self.assertEqual(field["value"],value)
        self.assertEqual(p.capability({"session":{}},p.Safe())["fields"]["output_modalities"],{"present":False,"type":"MISSING"})

    def test_safe_nested_capability(self):
        event={"session":{"audio":{"input":{"format":{"type":"audio/pcm","rate":44100},"turn_detection":None}},
                          "instructions":"hidden", "model":"gpt://private/model"}}
        saved=p.capability(event,p.Safe(("private",)))
        self.assertEqual(saved["fields"]["audio"]["value"],event["session"]["audio"])
        self.assertNotIn("private",json.dumps(saved))
        self.assertNotIn("hidden",json.dumps(saved))
        self.assertEqual(saved["fields"]["instructions"]["type"],"STRING")

    def test_event_counters_and_audio_never_saved(self):
        trace=p.Trace(p.Safe())
        for kind,category in [("response.audio.delta","AUDIO"),("response.output_audio.done","AUDIO"),
            ("response.output_audio_transcript.done","AUDIO"),("response.function_call_arguments.delta","TOOL"),
            ("input_audio_buffer.speech_started","VAD_SPEECH"),("session.updated","SESSION")]:
            trace.receive({"type":kind,"delta":"PRIVATE_AUDIO_BASE64"},1.)
            self.assertGreater(trace.counts[category],0)
        self.assertNotIn("PRIVATE_AUDIO_BASE64",json.dumps(trace.events))
        self.assertEqual(p.event_class({"type":"response.output_item.added","item":{"type":"function_call"}}),"TOOL")
        self.assertEqual(p.event_class({"type":"response.content_part.added","part":{"type":"audio"}}),"AUDIO")

    def test_raw_text_unmodified(self):
        trace=p.Trace(p.Safe())
        trace.receive({"type":"response.output_text.delta","delta":" Привет"},1.)
        trace.receive({"type":"response.output_text.delta","delta":"! \n"},2.)
        trace.receive({"type":"response.output_text.done","text":" Привет! \n"},3.)
        self.assertEqual("".join(trace.deltas)," Привет! \n")
        self.assertEqual(trace.terminals,[" Привет! \n"])

    def test_outbound_one_text_only(self):
        events=p.payloads("test")
        self.assertEqual(len(events),3)
        self.assertEqual(events[1]["item"]["content"],[{"type":"input_text","text":p.TEXT}])
        self.assertEqual(events[2]["response"]["output_modalities"],["text"])
        self.assertNotIn('"audio"',json.dumps(events))
        self.assertNotIn('"tools"',json.dumps(events))

    def test_no_voice_runtime_import_or_call(self):
        import ast
        tree=ast.parse(Path(p.__file__).read_text(encoding="utf-8"))
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertEqual([x for x in imports if x and x.startswith("orion.")],
            ["orion.yandex_realtime_provider","orion.windows_credentials","orion.launcher_cloud_voice_sections"])
        for name in ("sounddevice","speechkit","srs_radio","tool_gateway","planner","full_voice"):
            self.assertFalse(any(name in (x or "") for x in imports))


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def fake_run(self, *, fail=None, audio=False):
        sys.path.insert(0,str(p.ROOT))
        import aiohttp
        ident="test"
        events=[{"type":"session.created","session":{"output_modalities":["audio"]}},
                {"type":"session.updated","session":{"output_modalities":["text","audio"]}},
                {"type":"conversation.item.created","item":p.payloads(ident)[1]["item"]},
                {"type":"response.created","response":{"id":"resp-1"}},
                {"type":"response.output_text.delta","response_id":"resp-1","delta":" Текст. "},
                {"type":"response.output_text.done","response_id":"resp-1","text":" Текст. "},
                {"type":"response.done","response":{"id":"resp-1","status":"completed","output":[]}}]
        if fail is not None: events[fail:] = [{"type":"error","error":{"code":"invalid","message":"Api-Key secret"}}]
        if audio: events.insert(-1,{"type":"response.output_audio.delta","delta":"AUDIO_BYTES"})
        class WS:
            closed=False
            def __init__(self):self.sent=[];self.queue=list(events)
            async def send_json(self,value):self.sent.append(value)
            async def receive(self):
                value=self.queue.pop(0)
                return SimpleNamespace(type=aiohttp.WSMsgType.TEXT,json=lambda:value)
            async def close(self):self.closed=True
        ws=WS()
        class Session:
            closed=False
            async def ws_connect(self,*args,**kwargs):return ws
            async def close(self):self.closed=True
        session=Session()
        report={"probe_id":ident,"timestamps":{},"outbound":[],"provider_session_created":False}
        with patch.object(aiohttp,"ClientSession",return_value=session):await p.run(report,p.Safe(("secret",)),"fake","fake-folder")
        self.assertTrue(report["cleanup"]["websocket_closed"])
        self.assertTrue(report["cleanup"]["client_session_closed"])
        self.assertEqual(report["cleanup"]["remaining_async_tasks"],0)
        return report,ws

    async def test_multimodal_ack_continues_once(self):
        report,ws=await self.fake_run()
        self.assertEqual(report["verdict"],"PASS")
        self.assertEqual(report["text_raw"]," Текст. ")
        self.assertEqual(len(ws.sent),3)

    async def test_session_error_prevents_user_item(self):
        report,ws=await self.fake_run(fail=1)
        self.assertEqual(report["verdict"],"FAIL")
        self.assertEqual(len(ws.sent),1)
        self.assertNotIn("secret",json.dumps(report))

    async def test_item_error_prevents_response_request(self):
        report,ws=await self.fake_run(fail=2)
        self.assertEqual(len(ws.sent),2)
        self.assertEqual(report["verdict"],"FAIL")

    async def test_audio_is_not_protocol_pass(self):
        report,ws=await self.fake_run(audio=True)
        self.assertEqual(report["verdict"],"FAIL_UNEXPECTED_OUTPUT")
        self.assertEqual(report["event_counts"]["AUDIO"],1)
        self.assertNotIn("AUDIO_BYTES",json.dumps(report))


if __name__ == "__main__":
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    Path(__file__).with_name("offline-characterization.json").write_text(json.dumps({"tests":result.testsRun,
        "failures":len(result.failures),"errors":len(result.errors),"passed":result.wasSuccessful()},indent=2),encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)
