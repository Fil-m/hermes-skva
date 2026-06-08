#!/usr/bin/env python3
"""
SKVA Core Engine v4.1 — Markdown code blocks with filepath,
real context passing, fixed truncation, safe phase loading.
"""
import asyncio, json, os, sys, time, re
from pathlib import Path

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))

TOKEN_LIMIT = 32000
MAX_FILE_CHARS = 5000

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)

def count_tokens(text):
    """Approximate token count."""
    return len(text) // 4


# ──────────────────────────────────────────────
# Bug #2 fix: truncation-safe markdown parser
# ──────────────────────────────────────────────
def _parse_filepath_blocks(text):
    """
    Parse // filepath: blocks from markdown code fences.
    Handles truncated output where closing ``` is missing.
    Returns {path: content}
    """
    files = {}

    # Strategy 1: complete ```...``` blocks
    blocks = re.findall(r'```(?:\w+)?\n(.*?)```', text, re.DOTALL)
    for block in blocks:
        _extract_filepath(block, files)

    # Strategy 2: truncated block — last ``` without closing ```
    lines = text.split('\n')
    found_fence_open = False
    block_content = []
    for line in lines:
        if line.startswith('```') and not found_fence_open:
            found_fence_open = True
            block_content = []
            continue
        elif line.startswith('```') and found_fence_open:
            found_fence_open = False
            block_content = []
            continue
        if found_fence_open:
            block_content.append(line)

    if found_fence_open and block_content:
        remaining = '\n'.join(block_content)
        if re.search(r'(?://|#|<!--)\s*filepath:\s*\S+', remaining):
            _extract_filepath(remaining, files)

    return files


def _extract_filepath(block, files_dict):
    """Extract filepath from a single block content."""
    match = re.search(r'(?://|#|<!--)\s*filepath:\s*([^\n]+)', block)
    if match:
        path = match.group(1).strip()
        content_start = block.find(match.group(0)) + len(match.group(0))
        content = block[content_start:].strip()
        if content.endswith('```'):
            content = content[:-3].strip()
        files_dict[path] = content


def _parse_no_fence_filepath(text):
    """Fallback: standalone filepath lines (no code fence)."""
    files = {}
    lines = text.split('\n')
    current_path = None
    current_content = []
    for line in lines:
        fp_match = re.match(r'\s*(?://|#|<!--)\s*filepath:\s*(\S+)', line)
        if fp_match:
            if current_path and current_content:
                files[current_path] = '\n'.join(current_content)
            current_path = fp_match.group(1).strip()
            current_content = []
        elif current_path:
            current_content.append(line)
    if current_path and current_content:
        files[current_path] = '\n'.join(current_content)
    return files


# ──────────────────────────────────────────────
# Bug #4 fix: safe load_phase_context
# ──────────────────────────────────────────────
BINARY_EXTENSIONS = frozenset({
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp',
    '.zip', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.mp3', '.mp4', '.avi', '.mov', '.wav', '.ogg',
    '.pyc', '.pyo', '.pyd', '.so', '.dll', '.dylib',
    '.exe', '.msi', '.bin', '.o', '.a', '.lib',
})

SKIP_DIRS = frozenset({'node_modules', '.git', '__pycache__', '.venv', 'venv', 'dist', 'build', '.next', '.turbo', 'target'})


def _is_binary(path):
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


def load_phase_context(project_dir, phase, max_chars=12000):
    """Load artifacts from a phase with char limit.
    Safe: skips binary files, node_modules, .git, __pycache__.
    """
    phase_dir = Path(project_dir) / ".hermes" / "artifacts" / phase
    if not phase_dir.exists():
        return ""

    parts = []
    total = 0
    for f in sorted(phase_dir.rglob("*")):
        if not f.is_file():
            continue
        if _is_binary(f):
            continue
        rel = f.relative_to(phase_dir)
        parts_str = str(rel)
        if any(skip in parts_str.split(os.sep) for skip in SKIP_DIRS):
            continue
        if f.stat().st_size == 0:
            continue

        remaining = max_chars - total
        if remaining <= 0:
            break

        try:
            text = f.read_text(errors='replace')[:remaining]
        except (UnicodeDecodeError, PermissionError, OSError):
            continue

        parts.append(f"--- {rel} ---\n{text}")
        total += len(text)

    return "\n\n".join(parts)


# ──────────────────────────────────────────────
# Core: MarkdownAgent
# ──────────────────────────────────────────────
class MarkdownAgent:
    """Agent using markdown code blocks with // filepath: annotation."""

    def __init__(self, role, system_prompt, task_prompt, project_dir, timeout=300,
                 previous_code="", previous_error=""):
        self.role = role
        self.project_dir = Path(project_dir)
        self.timeout = timeout
        self.success = False
        self.error = ""
        self.files = {}
        self.summary = ""
        self.raw_output = ""

        # Bug #3 fix: dynamic token-aware retry context
        retry_context = ""
        if previous_code:
            pc_tokens = count_tokens(previous_code)
            budget = min(TOKEN_LIMIT, 3000)
            if pc_tokens > budget:
                truncated_code = previous_code[-budget*4:]
                log(f"retry context truncated {pc_tokens} -> {budget} tokens")
            else:
                truncated_code = previous_code

            retry_context = f"""
Попередня версія коду (має помилку):
{truncated_code}

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

        # Bug #2 fix: truncation-safe parsing
        self.files = _parse_filepath_blocks(self.raw_output)
        if not self.files:
            self.files = _parse_no_fence_filepath(self.raw_output)

        # Write files
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
            lower = self.raw_output.lower()
            if any(p in lower for p in ["i cannot", "i can't", "apologize", "unable to"]):
                self.error = "LLM refused"
            elif len(self.raw_output) < 50:
                self.error = "empty response"
            else:
                self.error = "no // filepath: blocks found"
                debug_path = self.project_dir / ".hermes" / "artifacts" / self.role / "_raw_output.txt"
                debug_path.write_text(self.raw_output[:10000])
            log(f"❌ {self.role} ({elapsed:.0f}s): {self.error}", "ERROR")

        return self


async def run_parallel(configs, project_dir):
    agents = [MarkdownAgent(
        role=cfg["role"],
        system_prompt=cfg.get("system_prompt", "Ти — AI асистент."),
        task_prompt=cfg["prompt"],
        project_dir=project_dir,
        timeout=cfg.get("timeout", 300)
    ) for cfg in configs]
    await asyncio.gather(*[a.run() for a in agents])
    return agents


# ──────────────────────────────────────────────
# Bug #3 fix: token-aware retry context builder
# ──────────────────────────────────────────────
def _build_retry_context(files_dict, error_msg, budget=4000):
    """Build retry context with token-aware allocation across files."""
    if not files_dict:
        return error_msg

    sorted_files = sorted(files_dict.items(), key=lambda x: len(x[1]))
    parts = []
    total_chars = 0

    for path, content in sorted_files:
        available = min(len(content), MAX_FILE_CHARS)
        remaining = budget * 4 - total_chars
        if remaining <= 0:
            break
        chunk = content[:min(available, remaining)]
        parts.append(f"=== {path} ===\n{chunk}")
        total_chars += len(chunk)

    code_block = "\n\n".join(parts)
    if error_msg:
        return f"{code_block}\n\nПомилка:\n{error_msg}"
    return code_block


async def auto_fix(role, task_prompt, project_dir, max_retries=3):
    """Auto-fix with REAL context passing and token-aware allocation."""
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

        previous_code = ""
        if agent.files:
            previous_code = _build_retry_context(agent.files, agent.error)
        previous_error = agent.error

    return agent


async def solo(request, project_dir="."):
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
    log("=== FACTORY ===")
    context = load_phase_context(project_dir, "council")
    task = f"{request}\n\nКонтекст:\n{context}" if context else request

    agent = await auto_fix("developer", task, project_dir, max_retries=3)

    if agent.success:
        (Path(project_dir) / ".hermes" / "signals" / ".factory.done").touch()
    return agent.success


async def rada_fabryka(request, project_dir="."):
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
        print("SKVA v4.1\nsolo 'task' [dir]\nrada 'task' [dir]")

if __name__ == "__main__":
    main()
