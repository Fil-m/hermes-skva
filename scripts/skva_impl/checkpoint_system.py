# SKVA checkpoint_system — auto-generated from TZ gap analysis
"""Checkpoint/recovery system per TZ section 4.1"""
import sys, os, json, time, asyncio
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

#!/usr/bin/env python3
"""
CheckpointSystem — recovery for SKVA DAG.
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from skva_core import log, StateMachine, ErrorCode

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
SKVA_DIR = ".skva"
CHECKPOINTS_DIR = ".skva/checkpoints"


@dataclass
class Checkpoint:
    phase: str
    data: Dict[str, Any]
    timestamp: float
    sequence: int


class CheckpointSystem:
    """Manages state checkpoints for SKVA DAG recovery and rollback."""

    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.checkpoints_path = self.base_path / CHECKPOINTS_DIR
        self.checkpoints_path.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._sequence_counter: Optional[int] = None

    async def _load_index(self) -> Dict[str, List[Dict]]:
        """Load checkpoint index from disk."""
        index_file = self.checkpoints_path / "index.json"
        if not index_file.exists():
            return {}
        try:
            async with self._lock:
                content = await asyncio.to_thread(index_file.read_text, encoding="utf-8")
                return json.loads(content)
        except Exception as e:
            log(f"Failed to load checkpoint index: {e}", "ERROR")
            return {}

    async def _save_index(self, index: Dict[str, List[Dict]]) -> None:
        """Save checkpoint index to disk."""
        index_file = self.checkpoints_path / "index.json"
        try:
            async with self._lock:
                await asyncio.to_thread(index_file.write_text, json.dumps(index, indent=2), encoding="utf-8")
        except Exception as e:
            log(f"Failed to save checkpoint index: {e}", "ERROR")
            raise

    async def _get_next_sequence(self) -> int:
        """Atomically get and increment global sequence number."""
        if self._sequence_counter is None:
            index = await self._load_index()
            sequences = [cp["sequence"] for cps in index.values() for cp in cps]
            self._sequence_counter = max(sequences) + 1 if sequences else 1
        else:
            self._sequence_counter += 1
        return self._sequence_counter

    async def save_checkpoint(self, phase: str, data: Dict[str, Any]) -> bool:
        """Save a new checkpoint for the given phase."""
        if not phase:
            log("Cannot save checkpoint: phase is required", "ERROR")
            return False

        timestamp = time.time()
        sequence = await self._get_next_sequence()
        cp_id = f"{int(timestamp)}_{sequence}"
        cp_file = self.checkpoints_path / f"{cp_id}.json"

        checkpoint = {
            "phase": phase,
            "data": data,
            "timestamp": timestamp,
            "sequence": sequence,
            "id": cp_id
        }

        try:
            async with self._lock:
                await asyncio.to_thread(cp_file.write_text, json.dumps(checkpoint, indent=2), encoding="utf-8")

                index = await self._load_index()
                if phase not in index:
                    index[phase] = []
                index[phase].append({
                    "id": cp_id,
                    "timestamp": timestamp,
                    "sequence": sequence
                })
                await self._save_index(index)

            log(f"Checkpoint saved: {phase} @ {cp_id}")
            return True
        except Exception as e:
            log(f"Failed to save checkpoint for phase '{phase}': {e}", "ERROR")
            return False

    async def load_checkpoint(self, phase: str) -> Optional[Dict[str, Any]]:
        """Load the latest checkpoint for the given phase."""
        if not phase:
            log("Cannot load checkpoint: phase is required", "ERROR")
            return None

        index = await self._load_index()
        if phase not in index or not index[phase]:
            log(f"No checkpoints found for phase: {phase}")
            return None

        # Sort by sequence (fallback) and timestamp
        sorted_cps = sorted(index[phase], key=lambda x: (x["timestamp"], x["sequence"]), reverse=True)
        latest_cp_id = sorted_cps[0]["id"]
        cp_file = self.checkpoints_path / f"{latest_cp_id}.json"

        if not cp_file.exists():
            log(f"Checkpoint file missing: {cp_file}", "ERROR")
            return None

        try:
            async with self._lock:
                content = await asyncio.to_thread(cp_file.read_text, encoding="utf-8")
                cp_data = json.loads(content)
                return cp_data.get("data")
        except Exception as e:
            log(f"Failed to load checkpoint {latest_cp_id}: {e}", "ERROR")
            return None

    async def get_latest(self) -> Optional[Checkpoint]:
        """Get the most recent checkpoint across all phases."""
        index = await self._load_index()
        all_entries = [(phase, cp) for phase, cps in index.items() for cp in cps]
        if not all_entries:
            return None

        latest = max(all_entries, key=lambda x: x[1]["timestamp"])
        phase, cp_info = latest
        return await self._read_checkpoint(cp_info["id"])

    async def _read_checkpoint(self, cp_id: str) -> Optional[Checkpoint]:
        """Read and parse a checkpoint by ID."""
        cp_file = self.checkpoints_path / f"{cp_id}.json"
        if not cp_file.exists():
            log(f"Checkpoint file not found: {cp_id}", "ERROR")
            return None
        try:
            content = await asyncio.to_thread(cp_file.read_text, encoding="utf-8")
            data = json.loads(content)
            return Checkpoint(
                phase=data["phase"],
                data=data["data"],
                timestamp=data["timestamp"],
                sequence=data["sequence"]
            )
        except Exception as e:
            log(f"Failed to read checkpoint {cp_id}: {e}", "ERROR")
            return None

    async def rollback(self, phase: str) -> bool:
        """Rollback to the previous checkpoint in the given phase."""
        if not phase:
            log("Cannot rollback: phase is required", "ERROR")
            return False

        index = await self._load_index()
        if phase not in index or len(index[phase]) < 2:
            log(f"Not enough checkpoints to rollback phase: {phase}")
            return False

        # Sort and get the one before latest
        sorted_cps = sorted(index[phase], key=lambda x: (x["timestamp"], x["sequence"]), reverse=True)
        cp_to_delete = sorted_cps[0]
        new_latest = sorted_cps[1]

        cp_file = self.checkpoints_path / f"{cp_to_delete['id']}.json"
        try:
            await asyncio.to_thread(cp_file.unlink, missing_ok=True)
            index[phase].remove(cp_to_delete)
            await self._save_index(index)

            log(f"Rolled back phase '{phase}' to checkpoint {new_latest['id']}")
            return True
        except Exception as e:
            log(f"Failed to rollback phase '{phase}': {e}", "ERROR")
            return False

    async def list_checkpoints(self) -> Dict[str, List[Dict]]:
        """List all checkpoints by phase."""
        index = await self._load_index()
        result = {}
        for phase, cps in index.items():
            result[phase] = sorted(
                [{k: cp[k] for k in ['id', 'timestamp', 'sequence']} for cp in cps],
                key=lambda x: (x["timestamp"], x["sequence"]),
                reverse=True
            )
        return result
