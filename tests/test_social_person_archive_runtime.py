from __future__ import annotations

import subprocess
from pathlib import Path


def test_social_person_archive_uses_shared_openclaw_profile_runtime() -> None:
    script = Path("/home/ubuntu/openclaw-agents/social/person-profile-skill/tools/person_archive.py")

    result = subprocess.run(
        ["python3", str(script), "--help"],
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert "--person PERSON" in result.stdout
