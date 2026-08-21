from __future__ import annotations

from array import array
from types import SimpleNamespace

import pytest

import orion.qwen_live_audio_core as core
from orion.qwen_audio_device import (
    AudioDeviceRateError,
    negotiate_audio_device_rate,
)
from orion.portaudio_devices import enumerate_portaudio_endpoints


class FakeSoundDevice:
    def __init__(
        self,
        *,
        input_default: int = 44_100,
        output_default: int = 48_000,
        accepted_input: set[int] | None = None,
        accepted_output: set[int] | None = None,
    ) -> None:
        self.devices = [
            {
                "name": "Dream Air Microphone",
                "hostapi": 0,
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": input_default,
            },
            {
                "name": "Dream Air Output",
                "hostapi": 0,
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": output_default,
            },
        ]
        self.accepted_input = (
            {input_default, core.QWEN_INPUT_RATE}
            if accepted_input is None
            else accepted_input
        )
        self.accepted_output = (
            {output_default, core.QWEN_OUTPUT_RATE}
            if accepted_output is None
            else accepted_output
        )
        self.input_checks: list[dict[str, object]] = []
        self.output_checks: list[dict[str, object]] = []

    @staticmethod
    def WasapiSettings(**kwargs: object) -> dict[str, object]:
        return dict(kwargs)

    def query_hostapis(self, index: int | None = None):  # noqa: ANN201
        hosts = [{"name": "MME"}]
        return hosts if index is None else hosts[index]

    def query_devices(self, index: int | None = None):  # noqa: ANN201
        return self.devices if index is None else self.devices[index]

    def check_input_settings(self, **kwargs: object) -> None:
        self.input_checks.append(kwargs)
        if kwargs["samplerate"] not in self.accepted_input:
            raise ValueError("input rate rejected")

    def check_output_settings(self, **kwargs: object) -> None:
        self.output_checks.append(kwargs)
        if kwargs["samplerate"] not in self.accepted_output:
            raise ValueError("output rate rejected")


@pytest.mark.parametrize(
    ("direction", "index", "default_rate", "protocol_rate"),
    [
        ("input", 0, 44_100, core.QWEN_INPUT_RATE),
        ("output", 1, 48_000, core.QWEN_OUTPUT_RATE),
    ],
)
def test_protocol_rate_is_used_before_reported_default(
    direction: str,
    index: int,
    default_rate: int,
    protocol_rate: int,
) -> None:
    sd = FakeSoundDevice()
    plan = negotiate_audio_device_rate(
        sd,
        direction=direction,  # type: ignore[arg-type]
        logical_device_id=f"selected-{direction}",
        device_index=index,
        protocol_rate=protocol_rate,
        extra_settings=None,
        extra_settings_mode="host_default",
    )

    assert plan.default_rate == default_rate
    assert plan.physical_rate == protocol_rate
    assert plan.attempted_rates == (protocol_rate,)
    assert plan.path == "direct_protocol_rate"
    assert not plan.resampling_required
    checks = sd.input_checks if direction == "input" else sd.output_checks
    assert checks == [
        {
            "device": index,
            "channels": 1,
            "dtype": "int16",
            "samplerate": protocol_rate,
            "extra_settings": None,
        }
    ]


@pytest.mark.parametrize(
    ("direction", "index", "protocol_rate"),
    [
        ("input", 0, core.QWEN_INPUT_RATE),
        ("output", 1, core.QWEN_OUTPUT_RATE),
    ],
)
def test_rejected_default_uses_first_valid_bounded_fallback(
    direction: str,
    index: int,
    protocol_rate: int,
) -> None:
    sd = FakeSoundDevice(
        input_default=32_000,
        output_default=32_000,
        accepted_input={48_000},
        accepted_output={48_000},
    )
    plan = negotiate_audio_device_rate(
        sd,
        direction=direction,  # type: ignore[arg-type]
        logical_device_id=f"selected-{direction}",
        device_index=index,
        protocol_rate=protocol_rate,
        extra_settings=None,
        extra_settings_mode="host_default",
    )

    assert plan.physical_rate == 48_000
    assert plan.attempted_rates == (protocol_rate, 32_000, 48_000)
    assert [item.rate for item in plan.rejected_rates] == [protocol_rate, 32_000]
    assert plan.path == "fallback_resampled"


@pytest.mark.parametrize(
    ("direction", "index", "protocol_rate", "expected_rates"),
    [
        ("input", 0, core.QWEN_INPUT_RATE, (16_000, 32_000, 48_000, 44_100)),
        ("output", 1, core.QWEN_OUTPUT_RATE, (24_000, 32_000, 48_000, 44_100)),
    ],
)
def test_all_candidates_rejected_has_direction_and_device_details(
    direction: str,
    index: int,
    protocol_rate: int,
    expected_rates: tuple[int, ...],
) -> None:
    sd = FakeSoundDevice(
        input_default=32_000,
        output_default=32_000,
        accepted_input=set(),
        accepted_output=set(),
    )

    with pytest.raises(AudioDeviceRateError) as caught:
        negotiate_audio_device_rate(
            sd,
            direction=direction,  # type: ignore[arg-type]
            logical_device_id=f"logical-{direction}",
            device_index=index,
            protocol_rate=protocol_rate,
            extra_settings=None,
            extra_settings_mode="host_default",
        )

    error = caught.value
    assert error.direction == direction
    assert error.device_index == index
    assert error.default_rate == 32_000
    assert error.attempted_rates == expected_rates
    assert direction.upper() in str(error)
    assert f"logical-{direction}" in str(error)
    assert "32_000" not in str(error)
    assert "32000" in str(error)


def test_core_resolves_input_and_output_rates_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sd = FakeSoundDevice(input_default=44_100, output_default=48_000)
    microphone, output = enumerate_portaudio_endpoints(sd)
    monkeypatch.setattr(
        core.audio_device_config,
        "state",
        lambda: SimpleNamespace(
            selection=SimpleNamespace(
                input_device_id=microphone.device_id,
                output_device_id=output.device_id,
                input_identity=microphone.identity(),
                output_identity=output.identity(),
            ),
            resolved_input=microphone,
            resolved_output=output,
        ),
    )

    resolved = core.QwenLiveAudioService()._resolve_audio(sd)

    assert resolved.input_native_rate == core.QWEN_INPUT_RATE
    assert resolved.output_native_rate == core.QWEN_OUTPUT_RATE
    assert resolved.input_rate_plan is not None
    assert resolved.output_rate_plan is not None
    assert resolved.input_rate_plan.logical_device_id == microphone.device_id
    assert resolved.output_rate_plan.logical_device_id == output.device_id
    assert resolved.input_extra_settings is None
    assert resolved.output_extra_settings is None


def test_independent_resampling_preserves_approximate_duration() -> None:
    input_pcm = array("h", range(1_764)).tobytes()
    qwen_input = core._resample_pcm16_mono(
        input_pcm, 44_100, core.QWEN_INPUT_RATE
    )
    assert len(qwen_input) // 2 == 640

    qwen_output = array("h", range(960)).tobytes()
    physical_output = core._resample_pcm16_mono(
        qwen_output, core.QWEN_OUTPUT_RATE, 48_000
    )
    assert len(physical_output) // 2 == 1_920
