from orion.desktop_launcher import RuntimeSynchronizedWindowsOrionProductLauncher
from orion.startup_health import StartupHealthReport, StartupHealthState


class _StatusVar:
    def __init__(self) -> None:
        self.value = None

    def set(self, value):  # noqa: ANN001
        self.value = value


class _Root:
    def __init__(self) -> None:
        self.after_calls: list[tuple[int, object]] = []

    def after(self, delay: int, callback):  # noqa: ANN001
        self.after_calls.append((delay, callback))


class _Core:
    def __init__(self, healthy: bool) -> None:
        self._healthy = healthy

    def healthy(self) -> bool:
        return self._healthy


def _launcher() -> RuntimeSynchronizedWindowsOrionProductLauncher:
    launcher = object.__new__(RuntimeSynchronizedWindowsOrionProductLauncher)
    launcher.status_var = _StatusVar()
    launcher.root = _Root()
    launcher.core = _Core(True)
    launcher.t = lambda key: key  # type: ignore[method-assign]
    return launcher


def test_poll_core_refreshes_health_and_reschedules() -> None:
    launcher = _launcher()
    refreshes: list[bool] = []
    launcher._refresh_health_async = lambda: refreshes.append(True)  # type: ignore[method-assign]

    launcher._poll_core()

    assert refreshes == [True]
    assert launcher.status_var.value == "status.core_ready"
    assert launcher.root.after_calls
    assert launcher.root.after_calls[0][0] == 1500


def test_polled_health_uses_product_renderer() -> None:
    launcher = _launcher()
    applied: list[StartupHealthReport] = []
    launcher._apply_health = lambda report: applied.append(report)  # type: ignore[method-assign]
    report = StartupHealthReport(state=StartupHealthState.HEALTHY, telemetry_connected=True)

    launcher._set_health(report)

    assert applied == [report]


def test_first_run_opens_only_for_action_required_health() -> None:
    launcher = _launcher()
    opened: list[bool] = []
    launcher._open_setup = lambda: opened.append(True)  # type: ignore[method-assign]

    launcher.health = StartupHealthReport(state=StartupHealthState.DEGRADED)
    launcher._maybe_first_run()
    assert opened == []

    launcher.health = StartupHealthReport(state=StartupHealthState.ACTION_REQUIRED)
    launcher._maybe_first_run()
    assert opened == [True]
