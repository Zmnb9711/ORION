from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.orion_development_console.context import VerificationContext
from tools.orion_development_console.engine import VerificationEngine
from tools.orion_development_console.ui import run_ui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ORION Development Console Phase 2")
    parser.add_argument("command", choices=("verify", "ui"), nargs="?", default="ui")
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    repository = args.repository.expanduser().resolve()
    if args.command == "ui":
        run_ui(repository)
        return 0
    report = VerificationEngine(VerificationContext.defaults(repository)).verify_everything()
    if args.json:
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(f"verification_id={report.verification_id}")
        print(f"overall_state={report.overall_state.value}")
        print(f"report={VerificationContext.defaults(repository).console_root / 'reports' / (report.verification_id + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
