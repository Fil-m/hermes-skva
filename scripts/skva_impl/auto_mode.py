# SKVA AutoMode — auto-generated
"""TZ gap closure"""
import sys, os, json, time, asyncio
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

#!/usr/bin/env python3
"""
SKVA AutoMode — Continuous autonomous operation with cycle management,
retrospective learning, and inbox monitoring.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import shutil
import time

from skva_core import (
    log,
    StateMachine,
    RunReport,
    CheckpointSystem,
    Gate,
    Budget,
    get_report
)
from .run_report import RunRecord


class AutoMode:
    """
    Autonomous mode engine for SKVA — manages full lifecycle of AI-driven
    software development cycles including planning, execution, feedback,
    and self-improvement.

    This class enables:
    - Single or multi-cycle project execution
    - Periodic inbox polling for new tasks
    - Graceful shutdown with state preservation
    - Inter-cycle retrospectives and skill updates
    - Git synchronization of artifacts and learnings

    All operations are async and non-blocking, suitable for long-running
    daemonized processes.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir).resolve()
        self.skva_dir = self.project_dir / SKVA_DIR
        self.inbox_dir = self.skva_dir / "inbox"
        self.checkpoints = CheckpointSystem(self.project_dir)
        self.budget = Budget()
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._state_machine: Optional[StateMachine] = None

    async def run_cycle(self, request: str, project_dir: Path) -> bool:
        """
        Execute one full DAG cycle: Council → Factory → Deploy → Verify.

        Args:
            request: Natural language description of desired outcome
            project_dir: Root directory for the project

        Returns:
            True if cycle completed successfully, False otherwise

        Raises:
            Exception if state machine fails to initialize
        """
        report = RunReport(project_dir=str(project_dir))
        try:
            with report:
                log("INFO", f"Starting cycle for request: {request}")
                self._state_machine = StateMachine(request, project_dir)
                await self._state_machine.load_state()

                # Council Phase
                report.start_phase("council", "analyze")
                council_done = await Gate("council.done").wait(timeout=600)
                if not council_done:
                    report.phase_error("council", "TIMEOUT", "Council phase did not complete in time")
                    return False
                report.end_phase("council", "success")

                # Factory Phase
                report.start_phase("factory", "implement")
                factory_verified = await Gate("factory.verified").wait(timeout=1800)
                if not factory_verified:
                    report.phase_error("factory", "VERIFICATION_FAILED", "Factory output failed QA")
                    return False
                report.end_phase("factory", "success")

                # Deploy Phase
                report.start_phase("deploy", "deploy")
                deploy_verified = await Gate("deploy.verified").wait(timeout=600)
                if not deploy_verified:
                    report.phase_error("deploy", "DEPLOY_FAILED", "Deployment verification failed")
                    return False
                report.end_phase("deploy", "success")

                # Final delivery
                log("SUCCESS", "Cycle completed successfully. Product delivered.")
                return True

        except Exception as e:
            log("ERROR", f"Cycle failed with exception: {str(e)}")
            if report:
                rec = report.start_agent("system", "orchestrator", "", 1, 1)
                report.complete_agent(
                    rec,
                    status="failed",
                    duration=0,
                    error_code="EXCEPTION",
                    error_msg=str(e)
                )
            return False

    async def run_continuous(self, request: str, project_dir: Path, cycles: int = 3) -> Dict[str, Any]:
        """
        Run multiple cycles with retrospective analysis and skill improvement between them.

        After each cycle:
        - Runs retrospective to analyze failures/successes
        - Pushes new skills to knowledge base
        - Commits changes to git
        - Adjusts strategy for next cycle

        Args:
            request: High-level goal to achieve
            project_dir: Working directory for the project
            cycles: Number of improvement cycles to attempt

        Returns:
            Summary dictionary with success status, cycle results, and final metrics
        """
        results = {
            "request": request,
            "cycles": [],
            "success": False,
            "start_time": time.time(),
            "final_artifacts": []
        }

        for i in range(1, cycles + 1):
            log("INFO", f"Starting cycle {i}/{cycles}")
            success = await self.run_cycle(request, project_dir)

            results["cycles"].append({
                "cycle": i,
                "success": success,
                "timestamp": time.time()
            })

            # If successful, no need to continue cycling
            if success:
                log("SUCCESS", f"Goal achieved in {i} cycles.")
                break

            # Inter-cycle improvement only if more cycles remain
            if i < cycles:
                log("INFO", f"Preparing for cycle {i + 1}...")
                await self._run_retro(request, project_dir)
                await self._skill_push(project_dir)
                await self._git_push(project_dir)

        # Final sync
        await self._git_push(project_dir)
        results["success"] = success
        results["duration"] = time.time() - results["start_time"]
        results["final_artifacts"] = await self._list_artifacts(project_dir)

        log("INFO", f"Continuous run completed in {results['duration']:.1f}s - "
                   f"Success: {results['success']}")
        return results

    async def _run_retro(self, request: str, project_dir: Path):
        """Run retrospective analysis to learn from previous cycle."""
        log("INFO", "Running retrospective analysis...")
        report = get_report()
        try:
            # Analyze run records for patterns
            failures = [r for r in (report.records if report else []) if r.status == "failed"]
            if failures:
                log("INFO", f"Found {len(failures)} failed attempts in history")
                # Save failure patterns for future avoidance
                retro_data = {
                    "request": request,
                    "failures": [
                        {
                            "node_id": f.node_id,
                            "role": f.role,
                            "error_code": f.error_code,
                            "error_message": f.error_message,
                            "tokens": f.total_tokens
                        }
                        for f in failures
                    ],
                    "timestamp": time.time()
                }
                retro_file = self.skva_dir / "learning" / "retrospectives.jsonl"
                retro_file.parent.mkdir(parents=True, exist_ok=True)
                with open(retro_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(retro_data, ensure_ascii=False) + "\n")
        except Exception as e:
            log("ERROR", f"Retrospective failed: {str(e)}")

    async def _skill_push(self, project_dir: Path):
        """Extract and store successful patterns as reusable skills."""
        log("INFO", "Pushing new skills to knowledge base...")
        try:
            skills_dir = self.skva_dir / "learning" / "skills"
            skills_dir.mkdir(parents=True, exist_ok=True)

            # Example: save any successfully applied patches
            patches_log = self.skva_dir / "patches_applied.jsonl"
            if patches_log.exists():
                successful_patches = []
                with open(patches_log, "r", encoding="utf-8") as f:
                    for line in f:
                        entry = json.loads(line)
                        if entry.get("success"):
                            successful_patches.append(entry)

                if successful_patches:
                    skill_file = skills_dir / f"patch_patterns_{int(time.time())}.json"
                    with open(skill_file, "w", encoding="utf-8") as f:
                        json.dump(successful_patches, f, indent=2, ensure_ascii=False)
                    log("INFO", f"Saved {len(successful_patches)} skill patterns")
        except Exception as e:
            log("ERROR", f"Skill push failed: {str(e)}")

    async def _git_push(self, project_dir: Path):
        """Commit and push all changes to remote git repository."""
        log("INFO", "Syncing changes to git...")
        try:
            if not (project_dir / ".git").exists():
                log("WARNING", "No git repo found, skipping git push")
                return

            # Stage all changes
            proc = await asyncio.create_subprocess_exec(
                "git", "add", ".",
                cwd=project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.wait()

            # Commit if changes exist
            proc = await asyncio.create_subprocess_exec(
                "git", "diff", "--cached", "--quiet",
                cwd=project_dir
            )
            has_changes = await proc.wait()

            if has_changes == 1:  # Changes present
                proc = await asyncio.create_subprocess_exec(
                    "git", "commit", "-m", "🤖 SKVA auto-commit: cycle update",
                    cwd=project_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode == 0:
                    log("INFO", "Changes committed")
                else:
                    log("ERROR", f"Git commit failed: {stderr.decode()}")
                    return

            # Push to origin
            proc = await asyncio.create_subprocess_exec(
                "git", "push", "origin", "main",
                cwd=project_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                log("SUCCESS", "Changes pushed to remote")
            else:
                log("ERROR", f"Git push failed: {stderr.decode()}")

        except Exception as e:
            log("ERROR", f"Git sync failed: {str(e)}")

    async def _list_artifacts(self, project_dir: Path) -> List[str]:
        """List all generated artifact files."""
        artifacts = []
        try:
            for ext in ["*.py", "*.js", "*.ts", "*.html", "*.css", "*.md", "*.json"]:
                artifacts.extend(list((project_dir).glob(f"**/{ext}")))
            # Exclude SKVA internal files
            artifacts = [str(a.relative_to(project_dir)) for a in artifacts
                        if SKVA_DIR not in str(a)]
        except Exception as e:
            log("ERROR", f"Failed to list artifacts: {str(e)}")
        return sorted(artifacts)

    async def watch(self, project_dir: Path, interval: int = 300):
        """
        Continuously monitor inbox for new requests and process them.

        Inbox messages should be text files with `.req` extension containing
        the natural language request.

        Processed requests are moved to `.done` or `.err`.

        Args:
            project_dir: Project root to watch
            interval: Polling interval in seconds
        """
        self.project_dir = Path(project_dir).resolve()
        self.inbox_dir = self.project_dir / SKVA_DIR / "inbox"
        self._running = True

        log("INFO", f"Starting inbox watcher at {self.inbox_dir}, polling every {interval}s")

        while self._running:
            try:
                if not self.inbox_dir.exists():
                    self.inbox_dir.mkdir(parents=True)
                    log("INFO", f"Created inbox directory: {self.inbox_dir}")

                # Find all request files
                req_files = list(self.inbox_dir.glob("*.req"))
                for req_file in req_files:
                    if not self._running:
                        break

                    try:
                        log("INFO", f"Processing request from {req_file.name}")
                        request = req_file.read_text(encoding="utf-8").strip()

                        # Generate unique project subdir
                        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', request[:50])
                        cycle_dir = self.project_dir / "projects" / safe_name
                        cycle_dir.mkdir(parents=True, exist_ok=True)

                        # Run continuous improvement cycle
                        result = await self.run_continuous(request, cycle_dir, cycles=3)

                        # Mark as done
                        done_file = req_file.with_suffix(".done")
                        req_file.rename(done_file)
                        log("SUCCESS", f"Request completed: {request[:60]}...")

                    except Exception as e:
                        log("ERROR", f"Failed to process {req_file}: {str(e)}")
                        err_file = req_file.with_suffix(".err")
                        req_file.rename(err_file)

                # Sleep between polls
                for _ in range(interval):
                    if not self._running:
                        break
                    await asyncio.sleep(1)

            except Exception as e:
                log("ERROR", f"Inbox watcher encountered error: {str(e)}")
                await asyncio.sleep(30)  # Backoff after failure

        log("INFO", "Inbox watcher stopped.")

    async def stop(self):
        """
        Gracefully shut down the AutoMode system.

        - Cancels all running tasks
        - Saves current state
        - Waits for cleanup
        - Ensures no orphaned processes
        """
        log("INFO", "Shutting down AutoMode gracefully...")
        self._running = False

        # Cancel all background tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        # Save final state
        if self._state_machine:
            await self._state_machine.save_state()
            self._state_machine = None

        # Final git sync
        try:
            await self._git_push(self.project_dir)
        except Exception as e:
            log("WARNING", f"Final git push failed during shutdown: {str(e)}")

        log("INFO", "AutoMode shutdown complete.")
