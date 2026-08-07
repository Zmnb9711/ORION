from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ComponentKind(StrEnum):
    CORE = "core"
    INTEGRATION = "integration"
    AIRCRAFT = "aircraft"
    KNOWLEDGE = "knowledge"
    VOICE = "voice"
    AI = "ai"
    TOOLS = "tools"


class InstallPreset(StrEnum):
    MINIMAL = "minimal"
    RECOMMENDED = "recommended"
    FULL_OFFLINE = "full_offline"
    CUSTOM = "custom"


class OrionComponent(BaseModel):
    component_id: str
    title: str
    kind: ComponentKind
    required: bool = False
    download_size_mb: int = Field(ge=0)
    installed_size_mb: int = Field(ge=0)
    dependencies: list[str] = Field(default_factory=list)
    description: str = ""


class InstallPlan(BaseModel):
    preset: InstallPreset
    requested: list[str]
    resolved: list[str]
    download_size_mb: int
    installed_size_mb: int


COMPONENTS: tuple[OrionComponent, ...] = (
    OrionComponent(component_id="orion-core", title="ORION Core", kind=ComponentKind.CORE, required=True, download_size_mb=40, installed_size_mb=150, description="Core services, configuration and runtime."),
    OrionComponent(component_id="dcs-integration", title="DCS Integration", kind=ComponentKind.INTEGRATION, download_size_mb=5, installed_size_mb=15, dependencies=["orion-core"], description="Flight Bridge, Mission Bridge, Export.lua and Mission Pack support."),
    OrionComponent(component_id="aircraft-fa18c", title="F/A-18C Aircraft Pack", kind=ComponentKind.AIRCRAFT, download_size_mb=10, installed_size_mb=30, dependencies=["orion-core", "dcs-integration"], description="Hornet cockpit adapters, calibration, procedures and semantic state."),
    OrionComponent(component_id="manual-fa18c", title="F/A-18C Manuals / Knowledge Pack", kind=ComponentKind.KNOWLEDGE, download_size_mb=30, installed_size_mb=45, dependencies=["aircraft-fa18c"], description="Optional local Hornet manuals and expanded offline knowledge."),
    OrionComponent(component_id="online-voice", title="Online Voice", kind=ComponentKind.VOICE, download_size_mb=5, installed_size_mb=20, dependencies=["orion-core"], description="Cloud-backed speech and AI connectors."),
    OrionComponent(component_id="offline-stt", title="Offline Speech Recognition", kind=ComponentKind.VOICE, download_size_mb=1500, installed_size_mb=1800, dependencies=["orion-core"], description="Local speech-to-text model pack."),
    OrionComponent(component_id="offline-tts", title="Offline Text-to-Speech", kind=ComponentKind.VOICE, download_size_mb=800, installed_size_mb=1100, dependencies=["orion-core"], description="Local speech synthesis model pack."),
    OrionComponent(component_id="offline-llm", title="Offline AI / LLM", kind=ComponentKind.AI, download_size_mb=8000, installed_size_mb=9000, dependencies=["orion-core"], description="Optional local language model pack."),
    OrionComponent(component_id="diagnostics-tools", title="Developer / Diagnostics Tools", kind=ComponentKind.TOOLS, download_size_mb=15, installed_size_mb=50, dependencies=["orion-core", "dcs-integration"], description="Calibration Wizard, diagnostics and extended logging tools."),
)


PRESETS: dict[InstallPreset, tuple[str, ...]] = {
    InstallPreset.MINIMAL: ("orion-core", "dcs-integration"),
    InstallPreset.RECOMMENDED: ("orion-core", "dcs-integration", "aircraft-fa18c", "online-voice"),
    InstallPreset.FULL_OFFLINE: (
        "orion-core", "dcs-integration", "aircraft-fa18c", "manual-fa18c",
        "offline-stt", "offline-tts", "offline-llm", "diagnostics-tools",
    ),
}


class ComponentRegistry:
    def __init__(self) -> None:
        self._components = {item.component_id: item for item in COMPONENTS}

    def list(self) -> list[OrionComponent]:
        return [item.model_copy(deep=True) for item in self._components.values()]

    def get(self, component_id: str) -> OrionComponent | None:
        item = self._components.get(component_id)
        return item.model_copy(deep=True) if item else None

    def plan(self, preset: InstallPreset, requested: list[str] | None = None) -> InstallPlan:
        selected = list(requested or PRESETS.get(preset, ()))
        if preset == InstallPreset.CUSTOM and not requested:
            selected = []
        resolved: list[str] = []
        visiting: set[str] = set()

        def add(component_id: str) -> None:
            if component_id in resolved:
                return
            component = self._components.get(component_id)
            if component is None:
                raise KeyError(component_id)
            if component_id in visiting:
                raise ValueError(f"Circular component dependency: {component_id}")
            visiting.add(component_id)
            for dependency in component.dependencies:
                add(dependency)
            visiting.remove(component_id)
            resolved.append(component_id)

        for component in self._components.values():
            if component.required:
                add(component.component_id)
        for component_id in selected:
            add(component_id)

        items = [self._components[item] for item in resolved]
        return InstallPlan(
            preset=preset,
            requested=selected,
            resolved=resolved,
            download_size_mb=sum(item.download_size_mb for item in items),
            installed_size_mb=sum(item.installed_size_mb for item in items),
        )


component_registry = ComponentRegistry()
