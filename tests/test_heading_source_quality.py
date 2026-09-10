"""Gate B source-quality bug: north zero and missing heading must differ."""
from pathlib import Path

import pytest

from orion.models import AircraftState, Position, TelemetryEnvelope
from orion.live_telemetry_store import LiveTelemetryStore
from orion.world_model import WorldModelFacade
from test_interaction_router import NOW


@pytest.mark.parametrize("heading,valid,status", [(0,True,"known"), (0,False,"unknown"), (0,None,"unknown"),
                                                  (137,None,"known"), (137,True,"known"), (137,False,"unknown")])
def test_heading_quality_does_not_replace_missing_with_north(heading, valid, status):
    store = LiveTelemetryStore()
    store.set(TelemetryEnvelope(state=AircraftState(aircraft_type="FA-18C_hornet",
        position=Position(latitude=42, longitude=43, altitude_m=1000), heading_deg=heading,
        heading_valid=valid, true_airspeed_mps=100)), received_at=NOW)
    out = WorldModelFacade(telemetry=store, clock=lambda:NOW).ownship()
    assert out.heading_deg.status == status
    assert out.heading_deg.value == (float(heading) if status == "known" else None)
    assert out.position.status == out.aircraft.status == "known"  # no false no-aircraft heartbeat
    assert out.heading_deg.generation == out.position.generation


def test_export_change_is_only_heading_quality_metadata():
    import subprocess
    root = Path(__file__).resolve().parents[1]
    current = (root/"dcs-export/Export.lua").read_text(encoding="utf-8")
    restored = current.replace('"heading_deg":%.2f,"heading_valid":%s,', '"heading_deg":%.2f,').replace(
        '        jsonBoolean(type(selfData.Heading) == "number"),\n', '')
    baseline = subprocess.check_output(['git','show','7b6981a:dcs-export/Export.lua'],cwd=root).decode()
    assert restored == baseline
    assert 'local heading = math.deg(selfData.Heading or 0) % 360' in current
    # The numeric output, timing, ports, callbacks and every other source remain literal.


def test_heading_quality_must_be_boolean():
    with pytest.raises(ValueError):
        AircraftState(aircraft_type="fixture", position=Position(latitude=0,longitude=0,altitude_m=0),
                      heading_deg=0, heading_valid="yes", true_airspeed_mps=0)


def test_telemetry_model_delta_is_one_optional_quality_field():
    import subprocess
    root = Path(__file__).resolve().parents[1]
    current = (root/"orion/models.py").read_text(encoding="utf-8")
    line = '    heading_valid: bool | None = Field(default=None, strict=True)\n'
    assert current.count(line) == 1
    assert current.replace(line, '') == subprocess.check_output(['git','show','7b6981a:orion/models.py'],cwd=root).decode()
