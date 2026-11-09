"""G0 runtime checks; no business data or visible desktop window is created."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PROBES = {
    "qt_offscreen": """
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication([])
label = QLabel('Kiểm tra môi trường bãi xe')
label.resize(480, 80)
label.show()
app.processEvents()
assert not label.grab().isNull()
label.close()
app.quit()
print('Qt widget rendered offscreen')
""",
    "sqlalchemy_transaction": """
from sqlalchemy import create_engine, event, text
engine = create_engine('sqlite:///:memory:')
@event.listens_for(engine, 'connect')
def enable_foreign_keys(connection, _):
    connection.execute('PRAGMA foreign_keys=ON')
with engine.begin() as conn:
    assert conn.scalar(text('PRAGMA foreign_keys')) == 1
    conn.execute(text('CREATE TABLE probe (id INTEGER PRIMARY KEY)'))
try:
    with engine.begin() as conn:
        conn.execute(text('INSERT INTO probe VALUES (1)'))
        raise RuntimeError('deliberate rollback')
except RuntimeError:
    pass
with engine.connect() as conn:
    assert conn.scalar(text('SELECT COUNT(*) FROM probe')) == 0
engine.dispose()
print('SQLite foreign keys and transaction rollback passed')
""",
    "torch_cpu": """
import torch
x = torch.tensor([[1.0, 2.0], [3.0, 4.0]], device='cpu')
assert torch.equal(x @ x, torch.tensor([[7.0, 10.0], [15.0, 22.0]]))
print(f'CPU tensor operation passed; torch={torch.__version__}; cuda_build={torch.version.cuda}')
""",
}


def run_probe(name: str, code: str) -> dict[str, object]:
    try:
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"name": name, "status": "failed", "error": str(error)}
    return {
        "name": name,
        "status": "passed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("reports/g0-environment.json"))
    args = parser.parse_args()
    versions: dict[str, str] = {}
    for name in (
        "PySide6",
        "SQLAlchemy",
        "torch",
        "torchvision",
        "ultralytics",
        "opencv-python",
        "numpy",
        "lap",
        "pytest",
        "ruff",
    ):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "missing"
    checks = [run_probe(name, code) for name, code in PROBES.items()]
    checks.insert(
        0,
        {
            "name": "python_311",
            "status": "passed" if sys.version_info[:2] == (3, 11) else "failed",
        },
    )
    report = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "scope": "G0 runtime smoke checks, not application acceptance or performance benchmark",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "versions": versions,
        "checks": checks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for check in checks:
        print(f"{check['name']}: {check['status']}")
    print(f"Report: {args.output}")
    return 0 if all(check["status"] == "passed" for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
