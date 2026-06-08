# SKVA git_sync — auto-generated from TZ gap analysis
"""Checkpoint/recovery system per TZ section 4.1"""
import sys, os, json, time, asyncio
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

import asyncio
import os
from pathlib import Path
from typing import Optional
from skva_core import log, StateMachine, MarkdownAgent, ErrorCode, NodeType


class GitSync:
    """Handles artifact synchronization via Git with full async support."""

    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.skva_dir = self.project_dir / SKVA_DIR
        self.repo_dir = self.project_dir
        self.git_dir = self.repo_dir / ".git"

    async def _run_git(self, *args: str, cwd: Optional[Path] = None) -> tuple[int, str, str]:
        """Execute git command asynchronously and return (returncode, stdout, stderr)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=(cwd or self.repo_dir),
            )
            stdout, stderr = await proc.communicate()
            return proc.returncode, stdout.decode().strip(), stderr.decode().strip()
        except Exception as e:
            log(f"Git command failed: {e}", "ERROR")
            return -1, "", str(e)

    async def init(self, project_dir: str, remote: str) -> bool:
        """Initialize a new Git repo and set remote."""
        try:
            self.repo_dir = Path(project_dir)
            self.skva_dir = self.repo_dir / SKVA_DIR
            self.git_dir = self.repo_dir / ".git"

            # Create skva dir if not exists
            self.skva_dir.mkdir(parents=True, exist_ok=True)

            # Init repo
            if not self.git_dir.exists():
                returncode, _, stderr = await self._run_git("init", cwd=self.repo_dir)
                if returncode != 0:
                    log(f"Failed to init git repo: {stderr}", "ERROR")
                    return False

            # Set remote
            returncode, _, stderr = await self._run_git("remote", "set-url", "origin", remote)
            if returncode != 0:
                # If no remote exists, add it
                returncode, _, stderr = await self._run_git("remote", "add", "origin", remote)
                if returncode != 0:
                    log(f"Failed to add git remote: {stderr}", "ERROR")
                    return False

            # Ensure .gitignore exists and contains common ignores
            gitignore = self.repo_dir / ".gitignore"
            ignores = {".skva/", "__pycache__/", "*.pyc", "node_modules/"}
            existing = set()
            if gitignore.exists():
                try:
                    content = gitignore.read_text(encoding="utf-8")
                    existing = {line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")}
                except Exception as e:
                    log(f"Could not read .gitignore: {e}", "ERROR")

            new_ignores = ignores - existing
            if new_ignores:
                with gitignore.open("a", encoding="utf-8") as f:
                    f.write("\n" + "\n".join(sorted(new_ignores)) + "\n")

            return True
        except Exception as e:
            log(f"Unexpected error during git init: {e}", "ERROR")
            return False

    async def status(self, project_dir: str) -> str:
        """Get git status."""
        try:
            self.repo_dir = Path(project_dir)
            returncode, stdout, stderr = await self._run_git("status", "--porcelain")
            if returncode == 0:
                return stdout
            else:
                log(f"Git status failed: {stderr}", "ERROR")
                return ""
        except Exception as e:
            log(f"Unexpected error during git status: {e}", "ERROR")
            return ""

    async def commit(self, project_dir: str, msg: str) -> bool:
        """Stage all changes and commit."""
        try:
            self.repo_dir = Path(project_dir)
            # Check if there is anything to commit
            status_output = await self.status(project_dir)
            if not status_output:
                return True  # Nothing to commit

            # Add all changes
            returncode, _, stderr = await self._run_git("add", ".")
            if returncode != 0:
                log(f"Git add failed: {stderr}", "ERROR")
                return False

            # Commit
            returncode, _, stderr = await self._run_git("commit", "-m", msg)
            if returncode != 0:
                log(f"Git commit failed: {stderr}", "ERROR")
                return False

            return True
        except Exception as e:
            log(f"Unexpected error during git commit: {e}", "ERROR")
            return False

    async def push(self, project_dir: str, msg: str) -> bool:
        """Commit and push to remote."""
        try:
            if not await self.commit(project_dir, msg):
                return False

            returncode, _, stderr = await self._run_git("push", "origin", "main")
            if returncode != 0:
                # Try master branch if main fails
                if "main" in stderr:
                    returncode, _, stderr = await self._run_git("push", "origin", "master")
                    if returncode != 0:
                        log(f"Git push failed: {stderr}", "ERROR")
                        return False
                else:
                    log(f"Git push failed: {stderr}", "ERROR")
                    return False

            return True
        except Exception as e:
            log(f"Unexpected error during git push: {e}", "ERROR")
            return False

    async def pull(self, project_dir: str) -> bool:
        """Pull latest changes from remote."""
        try:
            self.repo_dir = Path(project_dir)
            # Try main first, then master
            for branch in ["main", "master"]:
                returncode, _, stderr = await self._run_git("pull", "origin", branch)
                if returncode == 0:
                    return True
                if "not found" not in stderr and "fatal: couldn't find remote ref" not in stderr:
                    log(f"Git pull failed for {branch}: {stderr}", "ERROR")
                    return False
            return False
        except Exception as e:
            log(f"Unexpected error during git pull: {e}", "ERROR")
            return False
