"""Persistent, local-only Mentalab recording registry (no patient association)."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FILE_SUFFIXES = ("_ExG.csv", "_Meta.csv", "_Marker.csv", "_ORN.csv")
PREFIX_PATTERN = re.compile(r"^mentalab_.+_\d{8}_\d{6}_[0-9a-fA-F]{8}$")
MAX_MANIFEST_BYTES = 65536


class RecordingRegistry:
    def __init__(self, recordings_dir: Path):
        self.root = Path(recordings_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _prefix_from_csv(name: str) -> str | None:
        for suffix in FILE_SUFFIXES:
            if name.lower().endswith(suffix.lower()):
                prefix = name[: -len(suffix)]
                return prefix if PREFIX_PATTERN.fullmatch(prefix) else None
        return None

    def _safe_file(self, name: str) -> Path | None:
        if not name or Path(name).name != name or "\\" in name or "/" in name:
            return None
        path = self.root / name
        if path.is_symlink() or not path.is_file():
            return None
        if path.resolve().parent != self.root:
            return None
        return path

    def _manifest_path(self, prefix: str) -> Path:
        if not PREFIX_PATTERN.fullmatch(prefix):
            raise ValueError("Invalid recording prefix")
        return self.root / f"{prefix}.manifest.json"

    def _read_manifest(self, prefix: str) -> dict[str, Any] | None:
        path = self._manifest_path(prefix)
        safe = self._safe_file(path.name)
        if safe is None or safe.stat().st_size > MAX_MANIFEST_BYTES:
            return None
        try:
            record = json.loads(safe.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return None
        if not isinstance(record, dict) or record.get("filePrefix") != prefix:
            return None
        if not isinstance(record.get("recordingId"), str) or not record["recordingId"]:
            return None
        return record

    def _write_manifest(self, prefix: str, record: dict[str, Any]) -> None:
        target = self._manifest_path(prefix)
        if target.is_symlink():
            raise ValueError("Unsafe recording manifest path")
        payload = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
        if len(payload) > MAX_MANIFEST_BYTES:
            raise ValueError("Recording manifest too large")
        fd, temp_name = tempfile.mkstemp(prefix=".recording-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def register(self, recording_id: str, file_prefix: Path, started_at: str) -> None:
        prefix = Path(file_prefix).name
        if Path(file_prefix).resolve().parent != self.root:
            raise ValueError("Recording prefix outside local storage")
        if not recording_id or recording_id.startswith("legacy:"):
            raise ValueError("Invalid recording ID")
        existing = self._read_manifest(prefix)
        if existing and existing["recordingId"] != recording_id:
            raise ValueError("Recording manifest ID conflict")
        self._write_manifest(prefix, {
            "schemaVersion": 1,
            "recordingId": recording_id,
            "filePrefix": prefix,
            "startedAt": started_at,
            "stoppedAt": None,
        })

    def finalize(self, recording_id: str, file_prefix: Path, stopped_at: str) -> None:
        prefix = Path(file_prefix).name
        record = self._read_manifest(prefix)
        if record is None or record["recordingId"] != recording_id:
            raise ValueError("Recording manifest missing or mismatched")
        record["stoppedAt"] = stopped_at
        self._write_manifest(prefix, record)

    def _csv_files(self, prefix: str) -> list[dict[str, Any]]:
        files = []
        for suffix in FILE_SUFFIXES:
            path = self._safe_file(f"{prefix}{suffix}")
            if path is not None:
                files.append({"filename": path.name, "sizeBytes": path.stat().st_size})
        return files

    def list_recordings(self) -> list[dict[str, Any]]:
        prefixes: set[str] = set()
        for path in self.root.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            prefix = self._prefix_from_csv(path.name)
            if prefix:
                prefixes.add(prefix)

        records = []
        for prefix in prefixes:
            files = self._csv_files(prefix)
            if not files:
                continue
            manifest = self._read_manifest(prefix)
            legacy = manifest is None
            records.append({
                "recordingId": manifest["recordingId"] if manifest else f"legacy:{prefix}",
                "legacy": legacy,
                "patientLinked": False,  # This registry never asserts patient ownership.
                "filePrefix": prefix,
                "startedAt": manifest.get("startedAt") if manifest else None,
                "stoppedAt": manifest.get("stoppedAt") if manifest else None,
                "files": files,
            })
        return sorted(records, key=lambda item: item["filePrefix"], reverse=True)

    def resolve_file(self, recording_id: str, filename: str) -> Path:
        if not isinstance(recording_id, str) or not isinstance(filename, str):
            raise ValueError("Invalid download request")
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise ValueError("Invalid filename")
        prefix = self._prefix_from_csv(filename)
        if prefix is None:
            raise ValueError("Unexpected recording filename")
        manifest = self._read_manifest(prefix)
        expected_id = manifest["recordingId"] if manifest else f"legacy:{prefix}"
        if recording_id != expected_id:
            raise FileNotFoundError("Recording not found")
        path = self._safe_file(filename)
        if path is None:
            raise FileNotFoundError("Recording file not found")
        return path
