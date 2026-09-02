from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tools.orion_arch_guard.fingerprints import canonical_sha256
from tools.orion_development_console.collectors import (
    collect_dcs,
    collect_git,
    collect_history,
    collect_installed_orion,
    collect_local_data,
    collect_logs_and_evidence,
    collect_srs,
)
from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.models import (
    VerificationObservation,
    VerificationReport,
    VerificationState,
)
from tools.orion_development_console.store import VerificationReportStore


_ACTIONS_NOT_PERFORMED = [
    "git_fetch",
    "start_orion",
    "start_core",
    "start_launcher",
    "start_dcs",
    "start_srs",
    "open_microphone",
    "call_external_provider",
    "repair_or_install_files",
    "request_elevation",
    "live_dcs_readiness",
    "live_srs_readiness",
]


def apply_previous_fingerprint(
    current: VerificationObservation,
    previous: VerificationObservation | None,
) -> VerificationObservation:
    if (
        previous is not None
        and current.fingerprint
        and previous.fingerprint
        and current.fingerprint != previous.fingerprint
        and current.state is VerificationState.VERIFIED
    ):
        return current.model_copy(
            update={
                "state": VerificationState.CHANGED,
                "invalidated_by": ["fingerprint_changed_since_previous_verification"],
            }
        )
    return current


def age_observation(
    observation: VerificationObservation,
    *,
    now: datetime,
    max_age: timedelta,
) -> VerificationObservation:
    try:
        verified_at = datetime.fromisoformat(observation.verified_at)
    except ValueError:
        return observation.model_copy(
            update={
                "state": VerificationState.STALE,
                "invalidated_by": [*observation.invalidated_by, "invalid_verification_timestamp"],
            }
        )
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    if observation.state is VerificationState.VERIFIED and now.astimezone(UTC) - verified_at > max_age:
        return observation.model_copy(
            update={
                "state": VerificationState.STALE,
                "invalidated_by": [*observation.invalidated_by, "verification_age_exceeded"],
            }
        )
    return observation


def age_report(
    report: VerificationReport,
    *,
    now: datetime,
    max_age: timedelta = timedelta(hours=24),
) -> VerificationReport:
    return report.model_copy(
        update={
            "observations": [
                age_observation(item, now=now, max_age=max_age) for item in report.observations
            ]
        }
    )


class VerificationEngine:
    def __init__(
        self,
        context: VerificationContext,
        *,
        store: VerificationReportStore | None = None,
    ) -> None:
        self.context = context
        self.store = store or VerificationReportStore(context.console_root)

    def verify_everything(self, *, persist: bool = True) -> VerificationReport:
        previous = self.store.load_latest()
        git = collect_git(self.context)
        history = collect_history(self.context)
        logs, evidence = collect_logs_and_evidence(self.context, previous)
        repository_head = str(git.details.get("head") or "") or None
        observations = [
            git,
            history,
            logs,
            evidence,
            collect_installed_orion(self.context, repository_head),
            collect_local_data(self.context),
            collect_dcs(self.context),
            collect_srs(self.context),
        ]
        if previous is not None:
            observations = [
                apply_previous_fingerprint(item, previous.observation(item.subject))
                for item in observations
            ]
        generated_at = self.context.now().astimezone(UTC)
        identity_payload = {
            "generated_at": generated_at.isoformat(),
            "head": repository_head,
            "guard": self.context.architecture_report_id,
            "observations": [
                {"subject": item.subject, "fingerprint": item.fingerprint, "state": item.state.value}
                for item in observations
            ],
        }
        short_hash = canonical_sha256(identity_payload)[:8].casefold()
        verification_id = (
            f"OV-{generated_at.strftime('%Y%m%d-%H%M%S')}-"
            f"{(repository_head or 'unknown')[:7]}-{short_hash}"
        )
        report = VerificationReport(
            verification_id=verification_id,
            generated_at=generated_at.isoformat(),
            repository_head=repository_head,
            architecture_guard_report_id=self.context.architecture_report_id,
            architecture_guard_gate=str(history.details.get("last_guard_gate") or "UNKNOWN"),
            observations=observations,
            actions_not_performed=list(_ACTIONS_NOT_PERFORMED),
        )
        if persist:
            self.store.save(report)
        return report

    def cached_report(self) -> VerificationReport | None:
        report = self.store.load_latest()
        if report is None:
            return None
        return age_report(report, now=self.context.now())
