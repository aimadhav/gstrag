"""Verify historical source snapshots without relaxing held-out execution guards."""

import hashlib


def frozen_code_preserved(directory, freeze, current_code):
    # Snapshot use is only for checking history, never executing a new score.
    snapshot = directory / "frozen_code"
    source = snapshot if snapshot.is_dir() else current_code
    return all((source / name).is_file() and hashlib.sha256((source / name).read_bytes()).hexdigest() == checksum
               for name, checksum in freeze.get("code_sha256", {}).items())
