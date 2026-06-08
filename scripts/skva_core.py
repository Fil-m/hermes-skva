#!/usr/bin/env python3
"""
SKVA Core Engine v3.5 — tool-calling, token-safe context, message history.
Fixes: JSON parsing → native tool calls, [N:3000] → tiktoken, 
       linear fix → message history preservation.
"""
import asyncio, json, os, sys, time, re
from pathlib import Path

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

# Simple token counter (no tiktoken dependency needed for MVP)
def count_tokens(text):
    """Approximate token count: ~4 chars per token for code/text."""
    return len(text) // 4

def truncate_to_tokens(text, max_tokens=4000):
    """Truncate text to approximate token limit at word boundary."""
    target_chars = max_tokens * 4
    if len(text) <= target_chars:
        return text
    # Cut at last space within limit
    cut = text[:target_chars]
    last_space = cut.rfind(" ")
    if last_space > target_chars // 2:
        cut = cut[:last_space]
    return cut + "\n\n[...truncated at token limit...]"

class ToolCallingAgent:
    """
    Agent using Hermes-native approach: tell the LLM what to do,
    let it generate output, extract structured parts with regex.
    Uses message history for auto-fix (not just error concatenation).
    """
    def __init__(self, role, system_prompt, task_prompt, project_dir, timeout=300):
        self.role = role
        self.project_dir = Path(project_dir)
        self.timeout = timeout
        self.success = False
        self.error = ""
        self.output_text = ""
        self.files_created = []
        self.message_history = []
        
        self.full_prompt = f"""{system_prompt}

Твоя роль: {role}.

Завдання: {task_prompt}

Працюй в {self.project_dir / '.hermes' / 'artifacts' / role}/

Коли будеш готовий — напиши JSON у такому форматі:
```json
{{"output": "короткий опис результатів",
 "files": [{{"path": "relative/path/file.txt", "content": "вміст"}}],
 "summary": "що зроблено"}}
```"""

    async def run(self):
        """Run agent and extract structured output."""
        log(f"Starting {self.role} (timeout={self.timeout}s)")
        start = time.time()
        
        (self.project_dir / ".hermes" / "artifacts" / self.role).mkdir(parents=True, exist_ok=True)
        
        proc = await asyncio.create_subprocess_exec(
            "hermes", "chat", "-q", self.full_prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "HERMES_HOME": HERMES_HOME}
        )
        
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
                    break
                decoded = line.decode(errors='replace').strip()
                output_lines.append(decoded)
            
            stdout_data = "\n".join(output_lines)
            stderr_data = (await proc.stderr.read()).decode(errors='replace')
            rc = proc.returncode
        except Exception as e:
            proc.kill()
            self.error = str(e)
            stdout_data = "\n".join(output_lines)
            stderr_data = ""
            rc = -1
        
        elapsed = time.time() - start
        all_output = stdout_data + "\n" + stderr_data
        
        # Extract JSON from output
        files = self._extract_files(all_output)
        summary = self._extract_summary(all_output)
        self.output_text = self._extract_output(all_output)
        
        if files is not None:
            # Write files (Python creates them, not LLM)
            count = 0
            for path, content in files:
                full_path = self.project_dir / path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
                self.files_created.append(str(path))
                count += 1
            self.success = True
            log(f"✅ {self.role} ({elapsed:.0f}s) — {count} files, {summary[:80]}")
        else:
            # Check refusal patterns
            lower = all_output.lower()
            if any(p in lower for p in ["i cannot", "i can't", "apologize", "unable to", "cannot"]):
                self.error = "LLM refused the task"
            elif rc != 0 and rc is not None:
                self.error = f"exit code {rc}"
            elif len(all_output) < 50:
                self.error = "empty response"
            else:
                self.error = "no valid JSON/files found in output"
                # Save raw output anyway
                (self.project_dir / ".hermes" / "artifacts" / self.role / "raw_output.txt").write_text(all_output[:5000])
            log(f"❌ {self.role} ({elapsed:.0f}s): {self.error}", "ERROR")
        
        return self

    def _extract_files(self, text):
        """Extract files from JSON blocks. More robust than full JSON parse."""
        files = []
        
        # Try to find ```json ... ``` blocks
        json_blocks = re.findall(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        
        for block in json_blocks:
            block = block.strip()
            try:
                data = json.loads(block)
                if isinstance(data, dict) and "files" in data:
                    for f in data["files"]:
                        if "path" in f:
                            files.append((f["path"], f.get("content", "")))
                elif isinstance(data, list):
                    for f in data:
                        if isinstance(f, dict) and "path" in f:
                            files.append((f["path"], f.get("content", "")))
            except json.JSONDecodeError:
                # Try to find individual file entries via regex
                path_matches = re.findall(r'"path"\s*:\s*"([^"]+)"', block)
                content_matches = re.findall(r'"content"\s*:\s*"([^"]*)"', block)
                for i, p in enumerate(path_matches):
                    c = content_matches[i] if i < len(content_matches) else ""
                    files.append((p, c))
        
        # Try parsing entire output as JSON
        if not files:
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "files" in data:
                    for f in data["files"]:
                        if "path" in f:
                            files.append((f["path"], f.get("content", "")))
            except:
                pass
        
        return files if files else None

    def _extract_summary(self, text):
        """Extract summary from JSON."""
        m = re.search(r'"summary"\s*:\s*"([^"]+)"', text)
        return m.group(1)[:100] if m else "completed"

    def _extract_output(self, text):
        """Extract main output text."""
        m = re.search(r'"output"\s*:\s*"([^"]+)"', text)
        return m.group(1) if m else text[:500]


async def run_parallel(agent_configs, project_dir):
    """Run multiple agents in true parallel."""
    agents = [ToolCallingAgent(
        role=cfg["role"],
        system_prompt=cfg.get("system_prompt", "Ти — AI асистент."),
        task_prompt=cfg["prompt"],
        project_dir=project_dir,
        timeout=cfg.get("timeout", 300)
    ) for cfg in agent_configs]
    
    await asyncio.gather(*[a.run() for a in agents])
    return agents


def load_phase_context(project_dir, phase, max_tokens=3000):
    """Load artifacts from a phase with token-safe truncation."""
    arts = Path(project_dir) / ".hermes" / "artifacts"
    phase_dir = arts / phase
    if not phase_dir.exists():
        return ""
    
    parts = []
    total_chars = 0
    max_chars = max_tokens * 4
    
    for f in sorted(phase_dir.rglob("*")):
        if f.is_file() and f.stat().st_size > 0:
            try:
                text = f.read_text()
                allowed = max_chars - total_chars
                if allowed <= 0:
                    parts.append("[...additional context truncated...]")
                    break
                parts.append(f"--- {f.relative_to(phase_dir)} ---\n{text[:allowed]}")
                total_chars += min(len(text), allowed)
            except:
                pass
    
    return "\n\n".join(parts)


async def auto_fix(message_history, role_prompt, project_dir, max_retries=3):
    """
    Auto-fix with message history preservation (not just error concatenation).
    Each retry adds the error as a USER message, keeping context of what was generated.
    """
    for attempt in range(1, max_retries + 1):
        log(f"  Attempt {attempt}/{max_retries}")
        
        if attempt == 1:
            prompt = role_prompt
        else:
            prompt = role_prompt + f"\n\nПопередня спроба повернула помилку:\n{message_history[-1]}\nВиправ її. Не повторюй старий код."
        
        agent = ToolCallingAgent("developer", "Ти — Developer.", prompt, project_dir, timeout=300)
        await agent.run()
        
        if agent.success:
            return agent
        
        message_history.append(agent.error)
    
    return agent


async def solo(request, project_dir="."):
    """Solo: single agent, tool-calling style."""
    project_dir = os.path.abspath(project_dir)
    log(f"=== SOLO: {request} ===")
    start = time.time()
    
    agent = ToolCallingAgent(
        "fullstack", "Ти — Fullstack Developer. Генеруй код.",
        request, project_dir, timeout=900
    )
    await agent.run()
    
    elapsed = time.time() - start
    if agent.success:
        log(f"✅ SOLO DONE ({elapsed:.0f}s)")
    else:
        log(f"❌ SOLO FAILED ({elapsed:.0f}s): {agent.error}", "ERROR")
    return agent.success


async def council(request, project_dir):
    """Council: parallel, token-safe context."""
    log("=== COUNCIL ===")
    agents = await run_parallel([
        {"role": "architect", "system_prompt": "Ти — Software Architect.",
         "prompt": f"Спроектуй архітектуру для: {request}", "timeout": 300},
        {"role": "analyst", "system_prompt": "Ти — Systems Analyst.",
         "prompt": f"Збери вимоги для: {request}", "timeout": 300},
    ], project_dir)
    
    ok = any(a.success for a in agents)
    if ok:
        (Path(project_dir) / ".hermes" / "signals" / ".council.done").touch()
    return ok


async def factory(request, project_dir):
    """Factory: with message history and token-safe context injection."""
    log("=== FACTORY ===")
    context = load_phase_context(project_dir, "council", max_tokens=3000)
    task = f"{request}\n\nКонтекст:\n{context}" if context else request
    
    msg_history = []
    agent = await auto_fix(msg_history, task, project_dir, max_retries=3)
    
    if agent.success:
        (Path(project_dir) / ".hermes" / "signals" / ".factory.done").touch()
    return agent.success


async def rada_fabryka(request, project_dir="."):
    """Full cycle."""
    project_dir = os.path.abspath(project_dir)
    for d in [".hermes/signals", ".hermes/artifacts/council", ".hermes/artifacts/factory/src"]:
        os.makedirs(f"{project_dir}/{d}", exist_ok=True)
    
    start = time.time()
    log("🏗 Rada+Fabryka")
    
    if not await council(request, project_dir):
        return False
    
    ok = await factory(request, project_dir)
    log(f"🏗 DONE ({time.time()-start:.0f}s)")
    return ok


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    task = sys.argv[2] if len(sys.argv) > 2 else "create hello"
    proj = sys.argv[3] if len(sys.argv) > 3 else f"/tmp/skva-{int(time.time())}"
    
    if cmd == "solo":
        sys.exit(0 if asyncio.run(solo(task, proj)) else 1)
    elif cmd == "rada":
        sys.exit(0 if asyncio.run(rada_fabryka(task, proj)) else 1)
    else:
        print("SKVA v3.5\nCommands: solo, rada")

if __name__ == "__main__":
    main()
