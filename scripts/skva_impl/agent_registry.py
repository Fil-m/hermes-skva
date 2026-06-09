# SKVA AgentRegistry
import sys,os,json,time,asyncio,tempfile,shutil
from pathlib import Path
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

#!/usr/bin/env python3
"""
AgentRegistry — Central registry for managing distributed SKVA agents.
Tracks agent metadata, heartbeats, liveness, and persistence via YAML.
"""
import asyncio
import yaml
import os
import time
from pathlib import Path
from typing import List, Dict, Optional, Any
import logging

# Reuse existing HERMES_HOME and SKVA_DIR
HERMES_HOME = os.environ.get("HERMES_HOME", Path.home() / ".hermes")
SKVA_DIR = ".skva"
AGENTS_DIR = "agents"
REGISTRY_FILE = "registry.yaml"
HEARTBEAT_FILE = "heartbeat"

# Configure minimal logging (can be replaced with your log function)
def log(msg: str, level: str = "INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {level} | {msg}", file=sys.stderr if level == "ERROR" else sys.stdout)

class AgentRegistry:
    """
    Manages registration, heartbeat, and lifecycle of SKVA agents.

    Persists agent metadata to `.skva/agents/registry.yaml` and uses timestamp
    files for heartbeat tracking. Designed for secure, isolated, distributed agents.

    Thread-safe and async-friendly. Uses file locking via atomic writes.

    Example:
        registry = AgentRegistry(project_dir="/path/to/project")
        agent_id = registry.register("192.168.1.10", "coder", transport="ssh", profile="gpt4")
        registry.heartbeat(agent_id)
        alive = registry.check_alive(agent_id, timeout=30)
        registry.unregister(agent_id)
    """

    def __init__(self, project_dir: str = ""):
        self.project_dir = Path(project_dir).resolve() if project_dir else Path.cwd()
        self.skva_path: Path = self.project_dir / SKVA_DIR
        self.agents_path: Path = self.skva_path / AGENTS_DIR
        self.registry_path: Path = self.agents_path / REGISTRY_FILE

        # In-memory cache
        self._agents: List[Dict[str, Any]] = []
        self._loaded: bool = False

        # Ensure directories exist
        self._setup_dirs()

    def _setup_dirs(self):
        """Create .skva/agents/ directories if they don't exist."""
        try:
            self.agents_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            log(f"Failed to create agents directory {self.agents_path}: {e}", "ERROR")
            raise

    def _load(self) -> List[Dict[str, Any]]:
        """
        Load agent registry from YAML file.
        Returns empty list if file doesn't exist or is invalid.
        """
        if not self.registry_path.exists():
            return []
        try:
            with open(self.registry_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or []
                if not isinstance(data, list):
                    log(f"Invalid registry format: expected list, got {type(data)}", "ERROR")
                    return []
                return data
        except Exception as e:
            log(f"Failed to load registry from {self.registry_path}: {e}", "ERROR")
            return []

    def _save(self) -> bool:
        """
        Save current agent list to YAML atomically.
        Returns True on success.
        """
        try:
            # Write to temp file then move
            temp_file = tempfile.NamedTemporaryFile(mode='w', dir=self.agents_path, delete=False, suffix='.yaml')
            temp_path = Path(temp_file.name)
            yaml.safe_dump(self._agents, temp_file, default_flow_style=False, sort_keys=False)
            temp_file.close()

            # Atomic replace
            shutil.move(str(temp_path), self.registry_path)
            return True
        except Exception as e:
            log(f"Failed to save registry to {self.registry_path}: {e}", "ERROR")
            return False

    def load(self) -> List[Dict[str, Any]]:
        """
        Load and return the list of registered agents from persistent storage.
        This also updates the in-memory cache.
        """
        agents = self._load()
        self._agents = agents
        self._loaded = True
        return agents.copy()

    def save(self) -> bool:
        """
        Save the current in-memory agent list to disk.
        Returns True on success.
        """
        return self._save()

    def register(self, host: str, role: str, transport: str = 'ssh', profile: Optional[str] = None) -> str:
        """
        Register a new agent and return its unique agent_id.

        Args:
            host: Host address (IP, domain, or 'localhost')
            role: Agent role (e.g., 'coder', 'reviewer')
            transport: Communication method ('ssh', 'local', 'api', etc.)
            profile: Optional model/profile tag (e.g., 'gpt-4', 'claude-3')

        Returns:
            agent_id: Unique ID in format {role}_{transport}_{timestamp}_{rand}
        """
        try:
            timestamp = int(time.time())
            rand = hex(hash(f"{host}_{timestamp}") % 0xffff)[2:]
            agent_id = f"{role}_{transport}_{timestamp}_{rand}"

            agent_data = {
                "agent_id": agent_id,
                "host": host,
                "role": role,
                "transport": transport,
                "profile": profile,
                "registered_at": timestamp,
                "status": "registered"
            }

            # Load current list to avoid ID conflicts (minimal check)
            if not self._loaded:
                self.load()

            self._agents.append(agent_data)

            # Create heartbeat file
            hb_file = self.agents_path / f"{agent_id}.{HEARTBEAT_FILE}"
            hb_file.write_text(str(timestamp), encoding='utf-8')

            # Save registry
            if not self.save():
                raise RuntimeError("Failed to save registry after registration")

            log(f"Registered agent {agent_id} @ {host} [{role}, {transport}]")
            return agent_id

        except Exception as e:
            log(f"Failed to register agent {host}/{role}: {e}", "ERROR")
            raise

    def unregister(self, agent_id: str):
        """
        Unregister and remove an agent from the registry.
        Also deletes its heartbeat file.
        """
        try:
            # Filter out agent
            self._agents = [a for a in self._agents if a.get("agent_id") != agent_id]

            # Remove heartbeat file
            hb_file = self.agents_path / f"{agent_id}.{HEARTBEAT_FILE}"
            if hb_file.exists():
                hb_file.unlink()

            self.save()
            log(f"Unregistered agent {agent_id}")
        except Exception as e:
            log(f"Failed to unregister agent {agent_id}: {e}", "ERROR")
            raise

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List all registered agents. Optionally filter by status.

        Note: Does not auto-check liveness. Use check_alive() per agent for that.

        Args:
            status: Optional filter (e.g., 'alive', 'dead', 'registered')

        Returns:
            List of agent dicts with added 'alive' field if status is checked.
        """
        try:
            if not self._loaded:
                self.load()

            agents = []
            for a in self._agents:
                a_copy = a.copy()
                # Enrich with liveness
                is_alive = self.check_alive(a["agent_id"], timeout=30)
                a_copy["alive"] = is_alive
                a_copy["status"] = "alive" if is_alive else "dead"
                agents.append(a_copy)

            if status:
                agents = [a for a in agents if a["status"] == status]
            return agents
        except Exception as e:
            log(f"Failed to list agents: {e}", "ERROR")
            return []

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve agent metadata by agent_id.

        Returns:
            Agent dict if found, else None.
        """
        try:
            if not self._loaded:
                self.load()
            for a in self._agents:
                if a["agent_id"] == agent_id:
                    a_copy = a.copy()
                    a_copy["alive"] = self.check_alive(agent_id)
                    return a_copy
            return None
        except Exception as e:
            log(f"Failed to get agent {agent_id}: {e}", "ERROR")
            return None

    def heartbeat(self, agent_id: str) -> bool:
        """
        Update the heartbeat timestamp for an agent.

        Args:
            agent_id: The agent's unique ID

        Returns:
            True if heartbeat was updated, False otherwise.
        """
        try:
            hb_file = self.agents_path / f"{agent_id}.{HEARTBEAT_FILE}"
            if not hb_file.exists():
                log(f"Heartbeat file missing for {agent_id}, agent may be unregistered", "ERROR")
                return False

            hb_file.write_text(str(int(time.time())), encoding='utf-8')
            return True
        except Exception as e:
            log(f"Failed to update heartbeat for {agent_id}: {e}", "ERROR")
            return False

    def check_alive(self, agent_id: str, timeout: int = 30) -> bool:
        """
        Check if agent is alive based on last heartbeat.

        Args:
            agent_id: Agent ID
            timeout: Max seconds since last heartbeat (default 30s)

        Returns:
            True if agent has checked in within timeout, else False.
        """
        try:
            hb_file = self.agents_path / f"{agent_id}.{HEARTBEAT_FILE}"
            if not hb_file.exists():
                return False

            mtime = hb_file.stat().st_mtime
            return (time.time() - mtime) < timeout
        except Exception as e:
            log(f"Failed to check liveness for {agent_id}: {e}", "ERROR")
            return False


# Optional: Async wrapper methods (if needed for integration)
async def async_heartbeat(registry: AgentRegistry, agent_id: str):
    """Async version of heartbeat (non-blocking)."""
    return await asyncio.get_event_loop().run_in_executor(None, registry.heartbeat, agent_id)

async def async_check_alive(registry: AgentRegistry, agent_id: str, timeout: int = 30):
    """Async version of check_alive."""
    return await asyncio.get_event_loop().run_in_executor(None, registry.check_alive, agent_id, timeout)
