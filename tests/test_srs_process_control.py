from __future__ import annotations

import threading
from pathlib import Path

from orion.srs_process_control import (
    SrsExternalProcessController,
    SrsProcessKind,
    SrsProcessRecord,
    SrsProcessState,
    discover_srs_executable,
    sanitize_process_error,
    srs_discovery_candidates,
)


class Clock:
    def __init__(self) -> None:
        self.now = 10.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"external-srs-stub")
    return path


def test_discovery_prefers_explicit_paths_then_bounded_standard_locations(tmp_path) -> None:  # noqa: ANN001
    explicit = _exe(tmp_path / "portable" / "Server" / "SRS-Server.exe")
    program_files = tmp_path / "Program Files"
    standard = _exe(
        program_files / "DCS-SimpleRadio-Standalone" / "Client" / "SR-ClientRadio.exe"
    )

    assert discover_srs_executable(SrsProcessKind.SERVER, str(explicit)) == explicit
    assert discover_srs_executable(
        SrsProcessKind.CLIENT,
        environment={"ProgramFiles": str(program_files)},
    ) == standard
    candidates = srs_discovery_candidates(
        SrsProcessKind.CLIENT,
        {"ProgramFiles": str(program_files)},
    )
    assert len(candidates) == 2
    assert all(str(program_files) in str(candidate) for candidate in candidates)


def test_missing_or_wrong_executable_is_not_found(tmp_path) -> None:  # noqa: ANN001
    wrong = _exe(tmp_path / "SRS-Server-renamed.exe")
    controller = SrsExternalProcessController(inspector=lambda _name: ())

    assert controller.status(SrsProcessKind.SERVER, str(tmp_path / "missing.exe")).state is SrsProcessState.NOT_FOUND
    assert controller.status(SrsProcessKind.SERVER, str(wrong)).state is SrsProcessState.NOT_FOUND


def test_process_identity_requires_matching_image_and_full_path(tmp_path) -> None:  # noqa: ANN001
    expected = _exe(tmp_path / "expected" / "SRS-Server.exe")
    other = _exe(tmp_path / "other" / "SRS-Server.exe")
    controller = SrsExternalProcessController(
        inspector=lambda image: (SrsProcessRecord(44, str(other)),)
        if image == "SRS-Server.exe"
        else (),
    )

    assert controller.status(SrsProcessKind.SERVER, str(expected)).state is SrsProcessState.STOPPED


def test_server_launch_transitions_to_running_and_duplicate_is_not_started(tmp_path) -> None:  # noqa: ANN001
    server = _exe(tmp_path / "SRS" / "Server" / "SRS-Server.exe")
    records: list[SrsProcessRecord] = []
    launches: list[Path] = []

    def launch(path: Path) -> None:
        launches.append(path)
        records.append(SrsProcessRecord(101, str(path)))

    controller = SrsExternalProcessController(
        inspector=lambda _name: tuple(records),
        launcher=launch,
    )
    transitions = []
    first = controller.start_server(str(server), on_status=transitions.append)
    second = controller.start_server(str(server), on_status=transitions.append)

    assert first.state is SrsProcessState.RUNNING and first.pid == 101
    assert second.state is SrsProcessState.RUNNING
    assert launches == [server]
    assert [item.state for item in transitions[:2]] == [
        SrsProcessState.STARTING,
        SrsProcessState.RUNNING,
    ]


def test_concurrent_server_start_is_serialized_without_duplicate(tmp_path) -> None:  # noqa: ANN001
    server = _exe(tmp_path / "SRS" / "Server" / "SRS-Server.exe")
    records: list[SrsProcessRecord] = []
    launches: list[Path] = []
    launched = threading.Event()

    def launch(path: Path) -> None:
        launches.append(path)
        records.append(SrsProcessRecord(202, str(path)))
        launched.set()

    controller = SrsExternalProcessController(
        inspector=lambda _name: tuple(records),
        launcher=launch,
    )
    results: list[object] = []
    threads = [
        threading.Thread(target=lambda: results.append(controller.start_server(str(server))))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    assert launched.wait(1.0)
    for thread in threads:
        thread.join(1.0)

    assert len(results) == 2
    assert launches == [server]


def test_process_that_exits_immediately_is_not_reported_running(tmp_path) -> None:  # noqa: ANN001
    client = _exe(tmp_path / "Client" / "SR-ClientRadio.exe")
    server = _exe(tmp_path / "Server" / "SRS-Server.exe")
    clock = Clock()

    def inspect(image: str):  # noqa: ANN202
        if image == "SRS-Server.exe":
            return (SrsProcessRecord(1, str(server)),)
        return ()

    controller = SrsExternalProcessController(
        inspector=inspect,
        launcher=lambda _path: None,
        clock=clock,
        sleep=clock.sleep,
        startup_timeout=0.25,
    )
    result = controller.start_client(str(client), server_path=str(server))

    assert result.state is SrsProcessState.ERROR
    assert "did not remain running" in result.message


def test_client_requires_server_first_and_never_auto_starts_it(tmp_path) -> None:  # noqa: ANN001
    client = _exe(tmp_path / "Client" / "SR-ClientRadio.exe")
    server = _exe(tmp_path / "Server" / "SRS-Server.exe")
    launches: list[Path] = []
    controller = SrsExternalProcessController(
        inspector=lambda _name: (),
        launcher=launches.append,
    )

    result = controller.start_client(str(client), server_path=str(server))

    assert result.state is SrsProcessState.ERROR
    assert result.message == "Start SRS Server first."
    assert launches == []


def test_launch_error_is_sanitized_and_does_not_escape(tmp_path) -> None:  # noqa: ANN001
    server = _exe(tmp_path / "SRS-Server.exe")
    secret = "eam-secret"

    def fail(_path: Path) -> None:
        raise OSError(f"launch failed\n{secret}")

    controller = SrsExternalProcessController(inspector=lambda _name: (), launcher=fail)
    result = controller.start_server(str(server))

    assert result.state is SrsProcessState.ERROR
    assert "\n" not in result.message
    assert "launch failed" in result.message
    assert secret not in sanitize_process_error(OSError(secret), secret)


def test_server_and_client_statuses_are_independent(tmp_path) -> None:  # noqa: ANN001
    server = _exe(tmp_path / "Server" / "SRS-Server.exe")
    client = _exe(tmp_path / "Client" / "SR-ClientRadio.exe")
    controller = SrsExternalProcessController(
        inspector=lambda image: (SrsProcessRecord(22, str(server)),)
        if image == "SRS-Server.exe"
        else (),
    )

    assert controller.status(SrsProcessKind.SERVER, str(server)).state is SrsProcessState.RUNNING
    assert controller.status(SrsProcessKind.CLIENT, str(client)).state is SrsProcessState.STOPPED
    assert not hasattr(controller, "stop")
    assert not hasattr(controller, "terminate")
