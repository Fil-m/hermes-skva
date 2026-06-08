#!/usr/bin/env python3
"""
SKVA Core Engine v3 — asyncio parallel agents, JSON output, auto-fix loop.
"""
import asyncio, json, os, sys, time
from pathlib import Path

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

class AsyncAgent:
    """
    Async Hermes agent. Heartbeat = is it generating output?
    Output = JSON. Python creates files, not the LLM.
    """

    def __init__(self, role, system_prompt, task_prompt, project_dir, timeout=300):
        self.role = role
        self.project_dir = Path(project_dir)
        self.timeout = timeout
        self.result_json = None
        self.stdout_log = ""
        self.error = ""
        self.success = False

        # Build structured prompt: ask for JSON output
        self.full_prompt = f"""{system_prompt}

Твоя роль: {role}

Завдання: {task_prompt}

ВАЖЛИВО: Відповідай ТІЛЬКИ у форматі JSON:
{{
  "output": "твій результат тут",
  "files": [
    {{"path": "relative/path/to/file.txt", "content": "вміст файлу"}}
  ],
  "summary": "короткий опис що зроблено"
}}

Не додавай пояснень, не вітайся, не вибачайся. Тільки JSON."""

    async def run(self):
        """Run agent asynchronously."""
        log(f"Starting {self.role} (timeout={self.timeout}s)")
        start = time.time()
        artifacts_dir = self.project_dir / ".hermes" / "artifacts" / self.role
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "hermes", "chat", "-q", self.full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "HERMES_HOME": HERMES_HOME}
        )

        # Read stdout line by line (heartbeat = any output)
        heartbeat_count = 0
        output_lines = []
        try:
            while True:
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=self.timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    self.error = f"timeout after {self.timeout}s (no output)"
                    log(f"{self.role} TIMEOUT — killing", "ERROR")
                    break

                if not line:
                    break  # process done

                decoded = line.decode(errors='replace').strip()
                output_lines.append(decoded)
                heartbeat_count += 1

                # Heartbeat: every 10 lines of output = agent is alive
                if heartbeat_count % 10 == 0:
                    log(f"{self.role} heartbeat: {heartbeat_count} lines generated")

            # Process done — get remaining stdout + stderr
            stdout_data = "\n".join(output_lines)
            stderr_data = (await proc.stderr.read()).decode(errors='replace')
            rc = proc.returncode

        except Exception as e:
            proc.kill()
            self.error = str(e)
            log(f"{self.role} exception: {e}", "ERROR")
            stdout_data = "\n".join(output_lines)
            stderr_data = ""
            rc = -1

        elapsed = time.time() - start
        self.stdout_log = stdout_data + "\n" + stderr_data

        # Parse JSON from output
        json_found = self._extract_json(stdout_data)

        if json_found:
            self.result_json = json_found
            self.success = True
            self._write_files(json_found.get("files", []))
            log(f"✅ {self.role} ({elapsed:.0f}s) — {json_found.get('summary', 'no summary')[:100]}")
        else:
            # Check for common failure patterns
            output_lower = (stdout_data + " " + stderr_data).lower()
            if any(p in output_lower for p in ["i cannot", "i can't", "apologize", "unable to"]):
                self.error = "LLM refused the task"
                log(f"❌ {self.role}: LLM refused", "ERROR")
            elif rc != 0 and rc is not None:
                self.error = f"exit code {rc}"
                log(f"❌ {self.role}: exit code {rc}", "ERROR")
            elif heartbeat_count == 0:
                self.error = "no output generated"
                log(f"❌ {self.role}: no output", "ERROR")
            else:
                self.error = "no valid JSON in output"
                log(f"❌ {self.role}: no JSON — saving raw output", "WARN")
                # Save raw output anyway
                (self.project_dir / ".hermes" / "artifacts" / self.role / "raw_output.txt").write_text(stdout_data[:5000])
                self.success = False

        return self

    def _extract_json(self, text):
        """Find and parse JSON in LLM output."""
        # Try parsing entire output as JSON first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON between ```json and ```
        for marker in ["```json", "```"]:
            if marker in text:
                start = text.find(marker) + len(marker)
                end = text.find("```", start)
                if end > start:
                    try:
                        return json.loads(text[start:end].strip())
                    except json.JSONDecodeError:
                        pass

        # Try to find first { and last }
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end+1])
            except json.JSONDecodeError:
                pass

        return None

    def _write_files(self, files):
        """Python creates files from JSON, NOT the LLM."""
        for f in files:
            path = self.project_dir / f["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            content = f.get("content", "")
            path.write_text(content)
            log(f"  📄 {f['path']} ({len(content)}b)", "OK")

    def get_output_text(self):
        """Get the main output text from JSON result."""
        if self.result_json:
            return self.result_json.get("output", "")
        return ""

    def get_summary(self):
        """Get summary."""
        if self.result_json:
            return self.result_json.get("summary", "")
        return ""


async def run_parallel(agent_configs, project_dir):
    """
    Run multiple agents in TRUE parallel (asyncio.gather).
    Each gets its own subprocess.
    """
    agents = []
    for cfg in agent_configs:
        agent = AsyncAgent(
            role=cfg["role"],
            system_prompt=cfg.get("system_prompt", "Ти — AI асистент."),
            task_prompt=cfg["prompt"],
            project_dir=project_dir,
            timeout=cfg.get("timeout", 300)
        )
        agents.append(agent)

    # ALL agents start simultaneously
    tasks = [agent.run() for agent in agents]
    await asyncio.gather(*tasks)

    return agents


def load_previous_phase(project_dir, phase):
    """Load artifacts from previous phase to inject into next prompt."""
    arts = Path(project_dir) / ".hermes" / "artifacts"
    phase_dir = arts / phase
    if not phase_dir.exists():
        return ""
    
    content = []
    for f in sorted(phase_dir.rglob("*")):
        if f.is_file():
            try:
                text = f.read_text()[:2000]
                content.append(f"=== {f.relative_to(phase_dir)} ===\n{text}")
            except:
                pass
    return "\n\n".join(content)


async def auto_fix_loop(role, system_prompt, task_prompt, project_dir, max_retries=3):
    """
    Run agent with auto-fix loop: if output has errors, send back to fix.
    """
    for attempt in range(1, max_retries + 1):
        log(f"{role} attempt {attempt}/{max_retries}")
        
        # Add retry instruction for attempts > 1
        if attempt > 1:
            task = f"{task_prompt}\n\nПопередня спроба повернула помилку. Виправ її."
        else:
            task = task_prompt

        agent = AsyncAgent(role, system_prompt, task, project_dir, timeout=300)
        await agent.run()

        if agent.success:
            return agent

        if attempt < max_retries:
            log(f"{role} failed, retrying... ({agent.error})")

    return agent


async def solo(request, project_dir="."):
    """Solo: one agent, JSON output, Python handles files."""
    project_dir = os.path.abspath(project_dir)
    log(f"=== SOLO: {request} ===")
    start = time.time()

    agent = await auto_fix_loop(
        "fullstack",
        "Ти — Fullstack Developer. Генеруй код і файли.",
        request, project_dir
    )

    elapsed = time.time() - start
    if agent.success:
        log(f"✅ Solo DONE ({elapsed:.0f}s)")
    else:
        log(f"❌ Solo FAILED ({elapsed:.0f}s): {agent.error}", "ERROR")
    return agent.success


async def council(request, project_dir):
    """Council: Architect + Analyst in TRUE parallel via asyncio.gather."""
    log("=== COUNCIL (parallel) ===")
    agents = await run_parallel([
        {
            "role": "architect",
            "system_prompt": "Ти — Software Architect. Проектуєш систему.",
            "prompt": f"Спроектуй архітектуру для: {request}\nОпиши стек, компоненти, структуру.",
            "timeout": 300
        },
        {
            "role": "analyst",
            "system_prompt": "Ти — Systems Analyst. Збираєш вимоги.",
            "prompt": f"Збери вимоги для: {request}\nОпиши функціональні вимоги, обмеження, ризики.",
            "timeout": 300
        },
    ], project_dir)

    success = any(a.success for a in agents)
    if success:
        log("✅ Council DONE")
        # Signal done
        (Path(project_dir) / ".hermes" / "signals" / ".council.done").touch()
    else:
        log("❌ Council FAILED", "ERROR")
    return success


async def factory(request, project_dir):
    """Factory: Developer with auto-fix loop + context injection."""
    log("=== FACTORY ===")

    # Load previous phase context (Python reads, injects into prompt)
    council_context = load_previous_phase(project_dir, "council")
    context_prompt = f"{request}\n\nКонтекст з попередньої фази:\n{council_context[:3000]}"

    agent = await auto_fix_loop(
        "developer",
        "Ти — Developer. Пиши код. Повертай JSON з файлами.",
        context_prompt, project_dir
    )

    if agent.success:
        log("✅ Factory DONE")
        (Path(project_dir) / ".hermes" / "signals" / ".factory.done").touch()
        
        # Try to compile/test — auto-fix loop handles this
        await auto_verify_and_fix(project_dir)
    else:
        log("❌ Factory FAILED", "ERROR")
    return agent.success


async def auto_verify_and_fix(project_dir, max_attempts=3):
    """Try to run code, catch errors, send back to agent for fixing."""
    project = Path(project_dir)
    
    # Check if package.json exists (npm project)
    pkg = project / "package.json"
    if not pkg.exists():
        # Try python syntax check instead
        py_files = list(project.rglob("*.py"))
        for pf in py_files[:3]:
            r = await asyncio.create_subprocess_exec(
                "python3", "-m", "py_compile", str(pf),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await r.communicate()
            if r.returncode != 0:
                error_text = stderr.decode()[:500]
                log(f"  ❌ Python syntax error in {pf.name}", "WARN")
                # Send error back to developer agent for fixing
                fix_prompt = f"Файл {pf.name} має помилку:\n{error_text}\nВиправ її."
                await auto_fix_loop("developer", "Fix code errors.", fix_prompt, project_dir, max_attempts=2)
            else:
                log(f"  ✅ {pf.name} syntax OK")
        return

    # npm project
    r = await asyncio.create_subprocess_exec(
        "npm", "test",
        cwd=str(project),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await r.communicate()
    if r.returncode != 0:
        error_text = (stderr + stdout).decode()[:1000]
        log(f"  ❌ npm test failed", "WARN")
        # Auto-fix: send error to developer
        fix_prompt = f"Код має помилку:\n{error_text}\nВиправ її."
        await auto_fix_loop("developer", "Fix code errors.", fix_prompt, project_dir, max_attempts=2)
    else:
        log(f"  ✅ npm test passed")


async def rada_fabryka(request, project_dir="."):
    """Full Rada+Fabryka cycle with all improvements."""
    project_dir = os.path.abspath(project_dir)
    for d in [".hermes/signals/heartbeat", ".hermes/artifacts/council",
              ".hermes/artifacts/factory/src", ".hermes/artifacts/factory/tests",
              ".hermes/artifacts/deploy"]:
        os.makedirs(f"{project_dir}/{d}", exist_ok=True)
    
    start = time.time()
    log("🏗 Rada+Fabryka")
    
    # Phase 1: Council (parallel)
    council_ok = await council(request, project_dir)
    if not council_ok:
        log("❌ Council failed — aborting", "ERROR")
        return False
    
    # Phase 2: Factory (with context injection + auto-fix)
    factory_ok = await factory(request, project_dir)
    
    elapsed = time.time() - start
    log(f"🏗 DONE ({elapsed:.0f}s)")
    return factory_ok


def main():
    if len(sys.argv) < 2:
        print("SKVA v3 - async multi-agent production engine")
        print("Usage: python3 skva_core.py solo 'task' [dir]")
        print("       python3 skva_core.py rada 'task' [dir]")
        return
    
    cmd = sys.argv[1]
    task = sys.argv[2] if len(sys.argv) > 2 else "create hello world"
    proj = sys.argv[3] if len(sys.argv) > 3 else f"/tmp/skva-{int(time.time())}"

    if cmd == "solo":
        ok = asyncio.run(solo(task, proj))
        sys.exit(0 if ok else 1)
    elif cmd == "rada":
        ok = asyncio.run(rada_fabryka(task, proj))
        sys.exit(0 if ok else 1)
    else:
        print(f"Unknown: {cmd}")

if __name__ == "__main__":
    main()
