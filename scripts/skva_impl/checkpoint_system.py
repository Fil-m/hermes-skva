# SKVA CheckpointSystem
import sys,json,os,time,asyncio
from pathlib import Path
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

# checkpoint_system.py

import asyncio
import json
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CheckpointSystem:
    """
    Asynchronous checkpointing system for SKVA.
    Stores and retrieves state checkpoints in .skva/checkpoints/ as JSON files.
    Designed to integrate with a StateMachine for recovery.
    """

    def __init__(self, base_dir: str = ".skva"):
        self.base_dir = Path(base_dir)
        self.checkpoint_dir = self.base_dir / "checkpoints"
        self._init_directories()

    def _init_directories(self):
        """Ensure checkpoint directory exists."""
        try:
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create checkpoint directory {self.checkpoint_dir}: {e}")
            raise

    def _get_checkpoint_path(self, phase: str) -> Path:
        """Get the file path for a checkpoint by phase."""
        # Sanitize phase name to prevent path traversal
        safe_phase = "".join(c for c in phase if c.isalnum() or c in "._-")
        return self.checkpoint_dir / f"{safe_phase}.json"

    async def save_checkpoint(self, phase: str, data: Dict[str, Any]) -> bool:
        """
        Save a checkpoint for a given phase.
        Returns True on success, False on failure.
        """
        if not phase:
            logger.error("save_checkpoint: phase cannot be empty")
            return False

        checkpoint_path = self._get_checkpoint_path(phase)
        try:
            # Convert data to JSON-serializable format
            serializable_data = self._ensure_serializable(data)
            # Write asynchronously
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: checkpoint_path.write_text(json.dumps(serializable_data, indent=2), encoding="utf-8")
            )
            logger.info(f"Checkpoint saved for phase: {phase}")
            return True
        except Exception as e:
            logger.error(f"Failed to save checkpoint for phase '{phase}': {e}")
            return False

    async def load_checkpoint(self, phase: str) -> Optional[Dict[str, Any]]:
        """
        Load a checkpoint for a given phase.
        Returns the data dict if found, else None.
        """
        if not phase:
            logger.error("load_checkpoint: phase cannot be empty")
            return None

        checkpoint_path = self._get_checkpoint_path(phase)
        try:
            if not await asyncio.get_event_loop().run_in_executor(None, checkpoint_path.exists):
                logger.warning(f"Checkpoint not found for phase: {phase}")
                return None

            data_str = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: checkpoint_path.read_text(encoding="utf-8")
            )
            data = json.loads(data_str)
            logger.info(f"Checkpoint loaded for phase: {phase}")
            return data
        except Exception as e:
            logger.error(f"Failed to load checkpoint for phase '{phase}': {e}")
            return None

    async def get_latest(self) -> Optional[str]:
        """
        Returns the name of the latest (most recently modified) checkpoint phase.
        Returns None if no checkpoints exist.
        """
        try:
            if not await asyncio.get_event_loop().run_in_executor(None, self.checkpoint_dir.exists):
                return None

            def get_files():
                return [
                    f for f in self.checkpoint_dir.iterdir()
                    if f.is_file() and f.suffix == ".json"
                ]

            files = await asyncio.get_event_loop().run_in_executor(None, get_files)
            if not files:
                return None

            # Sort by modification time, descending
            latest_file = max(files, key=lambda f: f.stat().st_mtime)
            latest_phase = latest_file.stem  # filename without .json
            logger.info(f"Latest checkpoint: {latest_phase}")
            return latest_phase
        except Exception as e:
            logger.error(f"Failed to determine latest checkpoint: {e}")
            return None

    async def rollback(self, phase: str) -> bool:
        """
        Rollback by removing the checkpoint for the given phase.
        Returns True if deleted or didn't exist, False on error.
        """
        if not phase:
            logger.error("rollback: phase cannot be empty")
            return False

        checkpoint_path = self._get_checkpoint_path(phase)
        try:
            if await asyncio.get_event_loop().run_in_executor(None, checkpoint_path.exists):
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: checkpoint_path.unlink()
                )
                logger.info(f"Rolled back (deleted) checkpoint: {phase}")
            else:
                logger.info(f"No checkpoint to rollback for phase: {phase}")
            return True
        except Exception as e:
            logger.error(f"Failed to rollback checkpoint for phase '{phase}': {e}")
            return False

    async def list_checkpoints(self) -> List[str]:
        """
        List all available checkpoint phases.
        Returns a list of phase names (without extension).
        """
        try:
            if not await asyncio.get_event_loop().run_in_executor(None, self.checkpoint_dir.exists):
                return []

            def get_checkpoint_names():
                return [
                    f.stem for f in self.checkpoint_dir.iterdir()
                    if f.is_file() and f.suffix == ".json"
                ]

            phases = await asyncio.get_event_loop().run_in_executor(None, get_checkpoint_names)
            phases.sort()  # Alphabetical order
            logger.info(f"Listed {len(phases)} checkpoint(s): {phases}")
            return phases
        except Exception as e:
            logger.error(f"Failed to list checkpoints: {e}")
            return []

    def _ensure_serializable(self, data: Any) -> Any:
        """
        Recursively ensure data is JSON serializable.
        Converts unsupported types (e.g., Path, set) to serializable equivalents.
        """
        if isinstance(data, dict):
            return {str(k): self._ensure_serializable(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self._ensure_serializable(item) for item in data]
        elif isinstance(data, set):
            return [self._ensure_serializable(item) for item in sorted(data)]
        elif isinstance(data, (Path, os.PathLike)):
            return str(data)
        elif hasattr(data, "__dict__"):
            # Fallback for objects: use their dict if possible
            return self._ensure_serializable(data.__dict__)
        elif isinstance(data, (int, float, str, bool)) or data is None:
            return data
        else:
            logger.warning(f"Coercing non-serializable type {type(data)} to string")
            return str(data)
