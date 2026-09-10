"""Real Core/WorldModel/ToolGateway, controlled state and no external I/O."""
from datetime import timedelta
import json

import pytest

from orion.general_fact_registry import CATALOG, REGISTRY, CATALOG_VERSION, provider_catalog, require_exposed
from orion.general_fact_presentation import spoken_coordinates, unit_word
from orion.general_semantic_contracts import FactRequest, SemanticProposal, StateSummary, parse_semantic, provider_instructions
from orion.general_semantic_core import FactPlan, UnavailablePlan
from orion.live_telemetry_store import LiveTelemetryStore
from orion.models import AircraftState, Attitude, Position, TelemetryEnvelope
from orion.planner import PlannerCancellationToken
from orion.tool_gateway import build_tool_gateway
from orion.world_model import WorldModelFacade
from test_general_semantic import make


def fixture(*, aircraft="FA-18C_hornet", attitude=None, age=0, transform=None):
    core, hybrid, u, request, _ = make()
    store = LiveTelemetryStore()
    store.set(TelemetryEnvelope(state=AircraftState(
        aircraft_type=aircraft, position=Position(latitude=-42.123456, longitude=62.765432, altitude_m=1234.56),
        heading_deg=103.74, true_airspeed_mps=125, attitude=attitude or Attitude(pitch_deg=4.5, bank_deg=-12, yaw_deg=90),
        fuel={"INJECTED_EXTRA_TELEMETRY":999}, payload={"NEVER_SPEAK":999},
    )), received_at=request.created_at-timedelta(seconds=age))
    real = build_tool_gateway(world=WorldModelFacade(telemetry=store, clock=core.clock), clock=core.clock)
    class Counting:
        calls = []
        def definitions(self): return real.definitions()
        def execute(self, call):
            self.calls.append(call)
            result = real.execute(call)
            return transform(result) if transform else result
    gateway = Counting()
    core.gateway = hybrid.gateway = gateway
    return core, hybrid, u, request, gateway, store


def execute(bundle, ids=None, *, summary=False):
    core, hybrid, u, request, _, _ = bundle
    result = StateSummary(kind="STATE_SUMMARY") if summary else FactRequest(kind="FACT_REQUEST", capabilities=tuple(ids))
    return core.execute(u, SemanticProposal(request=request, response_id="fixture", result=result), PlannerCancellationToken(), hybrid)


@pytest.mark.parametrize("definition", CATALOG, ids=lambda item:item.capability)
@pytest.mark.parametrize("aircraft", ["FA-18C_hornet", "A-10C_2"])
def test_every_exposed_fact_has_real_gateway_mapping_and_output(definition, aircraft):
    bundle = fixture(aircraft=aircraft)
    out = execute(bundle, [definition.capability])
    assert out.text
    core, _, _, _, gateway, _ = bundle
    assert core.authorize(out) and len(gateway.calls) == 1
    if isinstance(out.plan, FactPlan) and out.plan.aircraft is None:
        assert {f.key for f in out.plan.facts} == set(definition.leaves)
        assert out.plan.receipt.actor_id == "general-semantic-core"
    assert "INJECTED_EXTRA" not in out.model_dump_json() and "NEVER_SPEAK" not in out.text
    core.context.accept(out)
    prompt = provider_instructions(core.context.project())
    assert "1234.56" not in prompt and "103.74" not in prompt and "INJECTED_EXTRA" not in prompt


def test_multi_fact_identity_coordinates_altitude_angles_one_coherent_read():
    bundle = fixture()
    out = execute(bundle, [d.capability for d in reversed(CATALOG)])
    assert isinstance(out.plan, FactPlan)
    assert out.plan.capabilities == tuple(d.capability for d in CATALOG)
    assert len(bundle[4].calls) == 1
    assert len({f.generation for f in out.plan.facts}) == 1
    assert len({f.observed_at for f in out.plan.facts}) == 1
    assert "F/A-18C Hornet" in out.text and "1235" in out.text and "103.74" in out.text
    assert "южной широты" in out.text and "восточной долготы" in out.text
    assert not any(symbol in out.text for symbol in ("°", "'", "NEVER_SPEAK"))
    assert len(out.text) <= 1000


def test_missing_leaf_is_not_zero_and_other_selected_fact_survives():
    bundle = fixture(attitude=Attitude(pitch_deg=None, bank_deg=0, yaw_deg=90))
    out = execute(bundle, ["ownship.pitch", "ownship.bank"])
    assert isinstance(out.plan, FactPlan)
    assert out.plan.unavailable[0].capability == "ownship.pitch"
    assert out.plan.unavailable[0].reason == "FACT_UNKNOWN"
    assert len(out.plan.facts) == 1 and out.plan.facts[0].value == 0
    assert "тангажа: неизвестно" in out.text and "крена 0.0 градусов" in out.text


@pytest.mark.parametrize("status,reason", [("stale","source_stale"), ("restricted","mission_truth_not_observation"),
                                          ("unknown","value_not_exported"), ("unavailable","source_not_connected")])
def test_partial_quality_does_not_speak_bad_values(status, reason):
    def transform(result):
        raw = result.model_dump(mode="json")
        fact = raw["data"]["snapshot"]["attitude"]
        fact.update(status=status, reason=reason)
        if status != "stale": fact["value"] = None
        statuses = raw["provenance"]["fact_statuses"]
        raw["provenance"]["fact_statuses"] = list(set(statuses+[status]))
        return type(result).model_validate(raw)
    out = execute(fixture(transform=transform), ["ownship.heading", "ownship.pitch"])
    assert isinstance(out.plan, FactPlan)
    assert len(out.plan.facts) == 1 and out.plan.facts[0].key == "ownship.heading_deg"
    assert out.plan.unavailable and "4.5" not in out.text


def test_whole_stale_snapshot_is_not_spoken():
    out = execute(fixture(age=10), ["ownship.pitch"])
    assert isinstance(out.plan, UnavailablePlan) and out.plan.reason == "FACT_STALE"


@pytest.mark.parametrize("path,value", [("authority","derived"), ("source","mission_store"),
                                        ("unit","radians"), ("generation",999)])
def test_selected_provenance_mismatch_rejected(path, value):
    def transform(result):
        raw = result.model_dump(mode="json")
        raw["data"]["snapshot"]["attitude"][path] = value
        return type(result).model_validate(raw)
    with pytest.raises(ValueError): execute(fixture(transform=transform), ["ownship.pitch"])


def test_catalog_is_metadata_only_and_unexposed_ids_fail_before_execution():
    assert len(CATALOG) == len(provider_catalog())
    for d in CATALOG:
        assert require_exposed(d.capability) is d and d.presentation and d.tool and d.leaves
    encoded = json.dumps(provider_catalog())
    for forbidden in ("LoGet", "state.", "permissions", "world.ownship.read", "handler", "value="):
        assert forbidden not in encoded
    for name, definition in REGISTRY.items():
        if not definition.exposed:
            with pytest.raises(ValueError): FactRequest(kind="FACT_REQUEST", capabilities=(name,))
    for bad in ({"kind":"FACT_REQUEST", "capabilities":["ownship.pitch"], "pitch":9},
                {"kind":"FACT_REQUEST", "capabilities":["ownship.unknown"]},
                {"kind":"STATE_SUMMARY", "all_fields":True}):
        with pytest.raises(ValueError): parse_semantic(json.dumps(bad))


def test_wrong_catalog_and_disabled_binding_do_not_read():
    bundle = fixture()
    core, hybrid, u, req, gateway, _ = bundle
    old = req.model_copy(update={"catalog_version":"old"})
    with pytest.raises(ValueError):
        core.execute(u, SemanticProposal(request=old, response_id="fixture",
            result=FactRequest(kind="FACT_REQUEST", capabilities=("ownship.pitch",))), PlannerCancellationToken(), hybrid)
    assert not gateway.calls
    gateway.definitions = lambda: ()
    with pytest.raises(ValueError): execute(bundle, ["ownship.pitch"])
    assert not gateway.calls and req.catalog_version == CATALOG_VERSION


def test_summary_is_registered_bounded_projection_not_raw_dump():
    from orion.general_semantic_core import SUMMARY_CAPABILITIES
    bundle = fixture()
    out = execute(bundle, summary=True)
    assert isinstance(out.plan, FactPlan) and out.plan.summary
    assert set(out.plan.capabilities) == set(SUMMARY_CAPABILITIES)
    assert set(out.plan.capabilities) < {d.capability for d in CATALOG}
    assert len(bundle[4].calls) == 1 and len(out.text) <= 1000
    assert "не полная оценка" in out.text
    assert "fuel" not in out.model_dump_json() and "INJECTED_EXTRA" not in out.model_dump_json()


@pytest.mark.parametrize("n,expected", [(1,"градус"),(2,"градуса"),(4,"градуса"),(5,"градусов"),
                                      (11,"градусов"),(12,"градусов"),(14,"градусов"),(21,"градус"),(22,"градуса"),(25,"градусов")])
def test_generic_russian_morphology(n, expected):
    assert unit_word(n, ("градус","градуса","градусов")) == expected


@pytest.mark.parametrize("lat,lon", [(0,0),(-0.0,-0.0),(90,180),(-90,-180),(42+59.9999/60,62),(-42,-62)])
def test_coordinate_boundaries_and_carry(lat, lon):
    text = spoken_coordinates(lat, lon)
    assert not any(c in text for c in "°'NESW")
    assert "60 минут" not in text and "-0" not in text
    assert ("южной широты" in text) == (lat < 0)
    assert ("западной долготы" in text) == (lon < 0)


@pytest.mark.parametrize("selection", [*(d.capability for d in CATALOG), "multi", "summary"])
def test_normal_full_voice_host_all_catalog_facts(monkeypatch, tmp_path, selection):
    import orion.full_voice_service as host
    import test_hybrid_host as legacy
    from orion.yandex_warm_aircraft_interpreter import WarmYandexAircraftInterpreter
    from test_general_semantic import SemanticWire
    from test_hybrid_aircraft import NOW
    # The old host harness is retained; only its external source gateway is replaced.
    store = LiveTelemetryStore()
    store.set(TelemetryEnvelope(state=AircraftState(aircraft_type="FA-18C_hornet",
        position=Position(latitude=42.1, longitude=43.2, altitude_m=1234.56), heading_deg=103.74,
        true_airspeed_mps=100, attitude=Attitude(pitch_deg=3, bank_deg=-4, yaw_deg=90))), received_at=NOW)
    real = build_tool_gateway(world=WorldModelFacade(telemetry=store, clock=lambda: NOW), clock=lambda: NOW)
    class Gateway:
        def __init__(self): self.calls = []
        def definitions(self): return real.definitions()
        def execute(self, call):
            self.calls.append(call)
            return real.execute(call)
    body = {"kind":"STATE_SUMMARY"} if selection == "summary" else {"kind":"FACT_REQUEST",
        "capabilities":[d.capability for d in CATALOG] if selection == "multi" else [selection]}
    owners = []
    class Configured:
        @classmethod
        def configured(cls, *args, **kwargs):
            owner = WarmYandexAircraftInterpreter(lambda: SemanticWire(json.dumps(body)), **kwargs)
            owners.append(owner)
            return owner
    monkeypatch.setattr(legacy, "Gateway", Gateway)
    monkeypatch.setattr(host, "WarmYandexAircraftInterpreter", Configured)
    captured = []
    legacy.test_gate10_normal_host_coexistence_and_single_owner(monkeypatch, tmp_path,
        "Report the selected current simulator properties.", True, 0, "active",
        general_kind="CORE_FACT_AUTHORITATIVE", expected_reads=1, capture=captured)
    assert owners[0].operation_count == 1 and not owners[0].owned
    assert captured[0]["tx_count"] == 1 and len(captured[0]["texts"]) == 1
    assert "1234.56" not in json.dumps(body) and not any("value" in key for key in body)


@pytest.mark.parametrize("bad", [True, "4.5", float("inf"), float("nan"), 91])
def test_selected_pitch_type_finite_and_range(bad):
    def transform(result):
        # Corrupt only the selected fact after the real gateway; no fake authority.
        raw = result.model_dump(mode="json")
        raw["data"]["snapshot"]["attitude"]["value"]["pitch_deg"] = bad
        # ToolData correctly refuses non-finite numbers before Core too.
        return type(result).model_validate(raw)
    with pytest.raises(ValueError): execute(fixture(transform=transform), ["ownship.pitch"])


def test_machine_manifest_is_exact_registry_projection():
    from pathlib import Path
    from scripts.general_fact_manifest import manifest
    stored = json.loads((Path(__file__).resolve().parents[1]/"docs/general-fact-surface.json").read_text(encoding="utf-8"))
    assert stored == manifest()
    assert len(REGISTRY) == stored["inventory_count"]
    assert all(d.exposed == (d in CATALOG) for d in REGISTRY.values())


def test_every_aircraft_model_top_level_field_was_audited():
    # A new raw source field requires an explicit inventory review, not auto exposure.
    audited = {"aircraft_type", "callsign", "position", "heading_deg", "heading_valid", "true_airspeed_mps",
        "vertical_speed_mps", "fuel_fraction", "fuel", "attitude", "velocity_vector", "airframe", "propulsion",
        "navigation", "radios", "payload", "warnings", "ew", "sensors", "capabilities", "cockpit_state",
        "diagnostics", "timestamp"}
    assert set(AircraftState.model_fields) == audited


def test_runtime_permission_rejection_cannot_become_a_fact():
    bundle = fixture()
    gateway = bundle[4]
    execute_original = gateway.execute
    def deny(call):
        # Exercise actual Gateway capability policy, not a forged success receipt.
        denied = call.model_copy(update={"context":call.context.model_copy(update={"allowed_capabilities":()})})
        return execute_original(denied)
    gateway.execute = deny
    with pytest.raises(ValueError, match="receipt"):
        execute(bundle, ["ownship.pitch"])
    assert not bundle[0].completed


def test_wrong_module_observed_fact_cannot_enter_common_catalog():
    for aircraft in ("FA-18C_hornet", "A-10C_2"):
        bundle = fixture(aircraft=aircraft)
        with pytest.raises(ValueError): execute(bundle, ["ownship.cockpit.comm1_preset"])
        assert not bundle[4].calls


def test_aircraft_epoch_resets_recent_not_persistent_context(monkeypatch, tmp_path):
    monkeypatch.setenv("ORION_RUNTIME_DIR", str(tmp_path))
    core = fixture()[0]
    first = core.context.project("Hornet")
    second = core.context.project("Warthog")
    assert second.revision > first.revision and not second.exchanges
    assert all(not item.applicability for item in CATALOG)  # common, not module state
