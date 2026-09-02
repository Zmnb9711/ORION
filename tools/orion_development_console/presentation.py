from __future__ import annotations

from typing import Any

from tools.orion_development_console.models import VerificationObservation, VerificationReport


SUBJECT_ORDER = (
    "git",
    "history",
    "logs",
    "evidence",
    "installed_orion",
    "local_data",
    "dcs_integration",
    "srs",
)

SUBJECT_TITLES = {
    "git": "Git",
    "history": "History",
    "logs": "Logs",
    "evidence": "Evidence",
    "installed_orion": "Installed ORION",
    "local_data": "Local ORION Data",
    "dcs_integration": "DCS Integration",
    "srs": "SRS",
}


def _short_sha(value: Any) -> str:
    return str(value)[:7] if value else "unknown"


def observation_summary(observation: VerificationObservation) -> str:
    details = observation.details
    if observation.subject == "git":
        cleanliness = "clean" if details.get("tracked_clean") and details.get("staged_clean") else "dirty"
        return f"{details.get('branch', 'unknown')} @ {_short_sha(details.get('head'))} — {cleanliness}; upstream cached"
    if observation.subject == "history":
        return f"{details.get('decision_register_count', 0)} decisions; {details.get('last_guard_report_id', 'no Guard report')}"
    if observation.subject == "logs":
        return f"{details.get('logs_discovered', 0)} known; {details.get('new_logs', 0)} new; {details.get('changed_logs', 0)} changed"
    if observation.subject == "evidence":
        return f"{details.get('evidence_zip_count', 0)} ZIP; {details.get('new_evidence', 0)} new"
    if observation.subject == "installed_orion":
        return (
            f"{details.get('installed_version') or 'version unknown'}; "
            f"Core {_short_sha(details.get('core_build_sha'))}; "
            f"repo {details.get('repository_comparison', 'UNKNOWN')}"
        )
    if observation.subject == "local_data":
        roots = details.get("roots") or []
        found = sum(bool(item.get("exists")) for item in roots if isinstance(item, dict))
        return f"{found}/{len(roots)} bounded roots found"
    if observation.subject == "dcs_integration":
        return (
            f"configured {observation.configured.value}; payload "
            f"{details.get('integration_comparison', 'UNKNOWN')}; live NOT_CHECKED"
        )
    if observation.subject == "srs":
        return (
            f"installed {observation.installed.value}; running {observation.running.value}; "
            "ready NOT_CHECKED"
        )
    return observation.state.value


def presentation_rows(report: VerificationReport) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for subject in SUBJECT_ORDER:
        observation = report.observation(subject)
        if observation is None:
            rows.append(
                {
                    "subject": subject,
                    "title": SUBJECT_TITLES[subject],
                    "state": "NOT_CHECKED",
                    "summary": "Not checked",
                    "verified_at": "—",
                }
            )
            continue
        rows.append(
            {
                "subject": subject,
                "title": SUBJECT_TITLES[subject],
                "state": observation.state.value,
                "summary": observation_summary(observation),
                "verified_at": observation.verified_at,
            }
        )
    return rows
