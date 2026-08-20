from __future__ import annotations

from enum import StrEnum
from threading import RLock

from pydantic import BaseModel


class OrionRuntimeModule(StrEnum):
    VIRTUAL_ATC = "virtual_atc"


class RuntimeModuleStatus(BaseModel):
    module: OrionRuntimeModule
    available: bool
    enabled: bool
    reason: str


class RuntimeModuleRegistry:
    """Minimal runtime capability gate for modules present in this build.

    This is deliberately not installer state.  It provides the boundary that a
    future installed/enabled module registry can drive without teaching Qwen
    about concrete subsystem classes.
    """

    def __init__(self) -> None:
        self._available: set[OrionRuntimeModule] = set()
        self._enabled: dict[OrionRuntimeModule, bool] = {}
        self._lock = RLock()

    def register(self, module: OrionRuntimeModule, *, enabled_by_default: bool = True) -> None:
        with self._lock:
            self._available.add(module)
            self._enabled.setdefault(module, enabled_by_default)

    def set_enabled(self, module: OrionRuntimeModule, enabled: bool) -> RuntimeModuleStatus:
        with self._lock:
            if module not in self._available:
                return RuntimeModuleStatus(
                    module=module,
                    available=False,
                    enabled=False,
                    reason="module_not_present_in_runtime",
                )
            self._enabled[module] = enabled
            return self.status(module)

    def status(self, module: OrionRuntimeModule) -> RuntimeModuleStatus:
        with self._lock:
            if module not in self._available:
                return RuntimeModuleStatus(
                    module=module,
                    available=False,
                    enabled=False,
                    reason="module_not_present_in_runtime",
                )
            enabled = self._enabled.get(module, True)
            return RuntimeModuleStatus(
                module=module,
                available=True,
                enabled=enabled,
                reason="available" if enabled else "module_disabled",
            )


runtime_modules = RuntimeModuleRegistry()
runtime_modules.register(OrionRuntimeModule.VIRTUAL_ATC)
