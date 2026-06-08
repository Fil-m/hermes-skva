#!/usr/bin/env python3
"""
SKVA Core Engine v4 — Markdown code blocks with filepath, 
real context passing (previous code injected into retry prompt).
"""
import asyncio, json, os, sys, time, re
from pathlib import Path

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def count_tokens(text):
    """Approximate token count."""
    return len(text) // 4

class MarkdownAgent:
    """
    Agent using markdown code blocks with // filepath: annotation.
    This is the industry standard (Aider, SWE-Agent format).
    No JSON escaping issues, no regex on fragile JSON.
    """

    def __init__(self, role, system_prompt, task_prompt, project_dir, timeout=300,
                 previous_code="", previous_error=""):
        self.role = role
        self.project_dir = Path(project_dir)
        self.timeout = timeout
        self.success = False
        self.error = ""
        self.files = {}  # {path: content}
        self.summary = ""
        self.raw_output = ""

        # Build prompt with previous code context if retry
        retry_context = ""
        if previous_code:
            retry_context = f"""
Попередня версія коду (має помилку):
{previous_code[:3000]}

Помилка:
{previous_error}

ВИПРАВ ЦЕЙ КОД. Не генеруй наново — виправ конкретну помилку.
"""

        artifacts_dir = self.project_dir / ".hermes" / "artifacts" / role

        self.full_prompt = f"""{system_prompt}

Твоя роль: {role}.
Проект: {self.project_dir}
Директорія: {artifacts_dir}

Завдання:
{task_prompt}

{retry_context}

ВАЖЛИВО — формат відповіді:
Для КОЖНОГО файлу, який треба створити, використовуй такий формат:

```language
// filepath: relative/path/to/file.extension
// content of the file
```

Наприклад:
```javascript
// filepath: src/index.html
<!DOCTYPE html>
<html><body>Hello</body></html>
```

Наприкінці напиши короткий підсумок.
Не додавай JSON. Не додавай пояснень до коду. Тільки код в блоках."""

    async def run(self):
        """Run agent, extract files from markdown blocks."""
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
                    self.error = f"timeout after {self.timeout}s"
                    break
                if not line:
                    break
                output_lines.append(line.decode(errors='replace'))
            
            self.raw_output = "".join(output_lines)
            stderr_data = (await proc.stderr.read()).decode(errors='replace')
            rc = proc.returncode
        except Exception as e:
            proc.kill()
            self.error = str(e)
            self.raw_output = "".join(output_lines)
            stderr_data = ""
            rc = -1

        elapsed = time.time() - start

        # Parse markdown code blocks for // filepath:
        self._parse_markdown_blocks()

        # Write files (Python creates them, NOT the LLM)
        if self.files:
            count = 0
            written_paths = []
            for path, content in self.files.items():
                full_path = self.project_dir / path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content)
                written_paths.append(str(path))
                count += 1
            self.success = True
            log(f"✅ {self.role} ({elapsed:.0f}s) — {count} files")
            for p in written_paths[:3]:
                log(f"  📄 {p}")
        else:
            # Check refusal
            lower = self.raw_output.lower()
            if any(p in lower for p in ["i cannot", "i can't", "apologize", "unable to"]):
                self.error = "LLM refused"
            elif len(self.raw_output) < 50:
                self.error = "empty response"
            else:
                self.error = "no // filepath: blocks found"
                # Save raw output for debugging
                debug_path = self.project_dir / ".hermes" / "artifacts" / self.role / "_raw_output.txt"
                debug_path.write_text(self.raw_output[:10000])
            log(f"❌ {self.role} ({elapsed:.0f}s): {self.error}", "ERROR")

        return self

    def _parse_markdown_blocks(self):
        """
        Parse markdown code blocks for // filepath: annotations.
        This is the Aider/SWE-Agent standard format.
        No JSON, no regex on code content, no escaping issues.
        """
        # Find all ```...``` blocks
        blocks = re.findall(r'```(?:\w+)?\n(.*?)```', self.raw_output, re.DOTALL)
        
        for block in blocks:
            # Look for // filepath: or # filepath: or <!-- filepath:
            match = re.search(r'(?://|#|<!--)\s*filepath:\s*([^\n]+)', block)
            if match:
                path = match.group(1).strip()
                # Content is everything after the filepath line
                content_start = block.find(match.group(0)) + len(match.group(0))
                content = block[content_start:].strip()
                # Remove trailing ``` if present
                if content.endswith('```'):
                    content = content[:-3].strip()
                self.files[path] = content

        # Also try standalone filepath: lines (without code block)
        if not self.files:
            lines = self.raw_output.split('\n')
            current_path = None
            current_content = []
            for line in lines:
                fp_match = re.match(r'\s*(?://|#|<!--)\s*filepath:\s*(\S+)', line)
                if fp_match:
                    # Save previous file
                    if current_path and current_content:
                        self.files[current_path] = '\n'.join(current_content)
                    current_path = fp_match.group(1).strip()
                    current_content = []
                elif current_path:
                    current_content.append(line)
            if current_path and current_content:
                self.files[current_path] = '\n'.join(current_content)


async def run_parallel(configs, project_dir):
    """Run multiple agents in true parallel."""
    agents = [MarkdownAgent(
        role=cfg["role"],
        system_prompt=cfg.get("system_prompt", "Ти — AI асистент."),
        task_prompt=cfg["prompt"],
        project_dir=project_dir,
        timeout=cfg.get("timeout", 300)
    ) for cfg in configs]
    await asyncio.gather(*[a.run() for a in agents])
    return agents


async def auto_fix(role, task_prompt, project_dir, max_retries=3):
    """
    Auto-fix with REAL context passing: previous code + error message
    injected into retry prompt, not just error text.
    """
    previous_code = ""
    previous_error = ""
    
    for attempt in range(1, max_retries + 1):
        log(f"  {role} attempt {attempt}/{max_retries}")
        
        agent = MarkdownAgent(
            role, "Ти — Developer. Пиши код.",
            task_prompt, project_dir, timeout=300,
            previous_code=previous_code,
            previous_error=previous_error
        )
        await agent.run()
        
        if agent.success:
            return agent
        
        # Save failed code for next attempt's context
        previous_code = ""
        if agent.files:
            previous_code = "\n\n".join(
                f"=== {path} ===\n{content[:1000]}"
                for path, content in agent.files.items()
            )
        previous_error = agent.error
    
    return agent


def load_phase_context(project_dir, phase, max_chars=12000):
    """Load artifacts from a phase with char limit."""
    phase_dir = Path(project_dir) / ".hermes" / "artifacts" / phase
    if not phase_dir.exists():
        return ""
    
    parts = []
    total = 0
    for f in sorted(phase_dir.rglob("*")):
        if f.is_file() and f.stat().st_size > 0:
            remaining = max_chars - total
            if remaining <= 0:
                break
            text = f.read_text()[:remaining]
            parts.append(f"--- {f.relative_to(phase_dir)} ---\n{text}")
            total += len(text)
    
    return "\n\n".join(parts)


async def solo(request, project_dir="."):
    """Solo: one agent, markdown file format."""
    project_dir = os.path.abspath(project_dir)
    log(f"=== SOLO: {request} ===")
    start = time.time()
    
    agent = MarkdownAgent(
        "fullstack", "Ти — Fullstack Developer.",
        request, project_dir, timeout=900
    )
    await agent.run()
    
    elapsed = time.time() - start
    if agent.success:
        log(f"✅ SOLO ({elapsed:.0f}s) — {len(agent.files)} files")
    else:
        log(f"❌ SOLO ({elapsed:.0f}s): {agent.error}", "ERROR")
    return agent.success


async def council(request, project_dir):
    """Council: parallel, markdown format, token-safe."""
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
    """Factory: with real context passing via auto_fix."""
    log("=== FACTORY ===")
    context = load_phase_context(project_dir, "council")
    task = f"{request}\n\nКонтекст:\n{context}" if context else request
    
    agent = await auto_fix("developer", task, project_dir, max_retries=3)
    
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
        print("SKVA v4\nsolo 'task' [dir]\nrada 'task' [dir]")

if __name__ == "__main__":
    main()
