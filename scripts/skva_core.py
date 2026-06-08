#!/usr/bin/env python3
"""
SKVA Core Engine v5 — State DAG orchestration, Error Taxonomy,
Search/Replace diffs, Resource Balancing, Secure Isolation.
"""
import asyncio, json, os, sys, time, re, difflib
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Callable
import tempfile, signal, stat, shutil

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
TOKEN_LIMIT = 32000
MAX_FILE_CHARS = 5000
SKVA_DIR = ".skva"


# ═══════════════════════════════════════════════════
# RUN REPORT — live progress + final statistics
# ═══════════════════════════════════════════════════

import contextvars
_report_var = contextvars.ContextVar("skva_report", default=None)

def get_report():
    """Get current report from asyncio context (thread-safe)."""
    return _report_var.get()

@dataclass
class RunRecord:
    node_id: str
    role: str
    model: str
    attempt: int
    max_retries: int
    status: str = "running"  # running | success | failed | skipped
    duration: float = 0.0
    files_written: int = 0
    patches_applied: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error_code: str = ""
    error_message: str = ""
    started_at: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost(self) -> float:
        """Rough cost in USD (assumes $2/M input, $8/M output for Qwen)."""
        return (self.input_tokens * 2 + self.output_tokens * 8) / 1_000_000


class RunReport:
    """Tracks all agent runs. Use as context manager: 'with RunReport():'"""

    def __init__(self, project_dir=""):
        self.records: List[RunRecord] = []
        self.start_time = time.time()
        self.node_times: Dict[str, float] = {}
        self.last_print = 0.0
        self.project_dir = project_dir

    def __enter__(self):
        self.token = _report_var.set(self)
        return self

    def __exit__(self, *exc):
        _report_var.reset(self.token)
        # Auto-save on exit
        if self.project_dir:
            self.save()

    def start_agent(self, node_id: str, role: str, model: str,
                    attempt: int, max_retries: int) -> RunRecord:
        rec = RunRecord(node_id, role, model, attempt, max_retries,
                        started_at=time.time())
        self.records.append(rec)
        _live(f"  🤖 {role} спроба {attempt}/{max_retries}" +
              (f" [{model}]" if model else ""))
        return rec

    def complete_agent(self, rec: RunRecord, status: str, duration: float,
                       files: int = 0, patches: int = 0,
                       input_tokens: int = 0, output_tokens: int = 0,
                       error_code: str = "", error_msg: str = ""):
        rec.status = status
        rec.duration = duration
        rec.files_written = files
        rec.patches_applied = patches
        rec.input_tokens = input_tokens
        rec.output_tokens = output_tokens
        rec.error_code = error_code
        rec.error_message = error_msg
        icon = "✅" if status == "success" else "❌" if status == "failed" else "⚠️"
        cost = rec.estimated_cost
        cost_str = f" (~${cost:.4f})" if cost > 0.001 else ""
        _live(f"  {icon} {rec.role} ({duration:.0f}с)"
              + (f" — {files} файлів, {patches} патчів" if files or patches else "")
              + (f", {rec.total_tokens} токенів{cost_str}" if rec.total_tokens else "")
              + (f" [{error_code}]" if error_code else ""))
        self.save()

    def add_tokens(self, rec: RunRecord, input_t: int, output_t: int):
        rec.input_tokens += input_t
        rec.output_tokens += output_t

    def start_phase(self, node_id: str, node_type: str):
        icons = {"analyze": "🔍", "design": "🎨", "implement": "💻",
                 "review": "👁", "fix": "🔧", "deploy": "🚀",
                 "done": "✅", "error": "❌"}
        icon = icons.get(node_type, "🏗")
        _live(f"\n{icon} Фаза: {node_type} ({node_id})")
        self.node_times[node_id] = time.time()

    def end_phase(self, node_id: str, status: str):
        elapsed = time.time() - self.node_times.get(node_id, time.time())
        _live(f"  {'✅' if status == 'success' else '❌'} Фаза завершена за {elapsed:.0f}с")

    def phase_error(self, node_id: str, error_code: str, error_msg: str):
        _live(f"  ⚠️ Помилка: [{error_code}] {error_msg[:120]}")

    def resource_status(self, capacity: int, active: int):
        now = time.time()
        if now - self.last_print < 30:
            return
        self.last_print = now
        elapsed = now - self.start_time
        total_files = sum(r.files_written for r in self.records)
        total_attempts = sum(1 for r in self.records if r.status != "running")
        _live(f"  ⚡ Ресурси: {active} активних, макс {capacity}"
              f" | 📄 Файлів: {total_files}"
              f" | 🤖 Спроби: {total_attempts}"
              f" | ⏱ {elapsed:.0f}с")

    def save(self):
        """Persist report to .skva/report.json (survives Ctrl+C)."""
        if not self.project_dir:
            return
        report_dir = Path(self.project_dir) / SKVA_DIR
        report_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "start_time": self.start_time,
            "records": [{
                "node_id": r.node_id, "role": r.role, "model": r.model,
                "attempt": r.attempt, "max_retries": r.max_retries,
                "status": r.status, "duration": r.duration,
                "files_written": r.files_written,
                "patches_applied": r.patches_applied,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "error_code": r.error_code,
                "error_message": r.error_message[:200],
            } for r in self.records],
        }
        with open(report_dir / "report.json", "w") as f:
            json.dump(data, f, indent=2)

    def print_final_summary(self):
        elapsed = time.time() - self.start_time
        total_agents = len(self.records)
        success_agents = sum(1 for r in self.records if r.status == "success")
        failed_agents = sum(1 for r in self.records if r.status == "failed")
        total_files = sum(r.files_written for r in self.records)
        total_retries = sum(1 for r in self.records if r.attempt > 1)
        total_tok = sum(r.total_tokens for r in self.records)
        total_cost = sum(r.estimated_cost for r in self.records)

        _live("\n" + "═" * 55)
        _live("📊  ЗВІТ ПРО ВИКОНАННЯ")
        _live("═" * 55)
        _live(f"⏱  Загальний час:    {elapsed:.0f}с ({elapsed/60:.1f}хв)")
        _live(f"🤖  Агентів запущено: {total_agents}")
        _live(f"✅  Успішно:          {success_agents}")
        _live(f"❌  Помилок:          {failed_agents}")
        _live(f"📄  Файлів створено:  {total_files}")
        _live(f"🔄  Retry:            {total_retries}")
        _live(f"🔤  Токенів:          {total_tok:,} (~${total_cost:.4f})")
        _live(f"\n📋  Деталі по фазам:")
        for rec in self.records:
            retry_info = f" (retry {rec.attempt}/{rec.max_retries})" if rec.attempt > 1 else ""
            icon = "✅" if rec.status == "success" else "❌"
            fi = f", {rec.files_written} файлів, {rec.patches_applied} патчів" if rec.files_written or rec.patches_applied else ""
            ti = f", {rec.total_tokens} ткн" if rec.total_tokens else ""
            ei = f" [{rec.error_code}] {rec.error_message[:60]}" if rec.error_code else ""
            _live(f"  {icon} {rec.role}{retry_info}: {rec.duration:.0f}с{fi}{ti}{ei}")
        if failed_agents:
            _live(f"\n⚠️  Помилки:")
            for rec in self.records:
                if rec.status == "failed" and rec.error_code:
                    _live(f"  [{rec.error_code}] {rec.error_message[:120]}")
        _live("═" * 55)
        _live(f"💾 Звіт збережено: .skva/report.json\n")


def _live(msg: str):
    """User-facing progress message. Goes to stdout, always visible."""
    print(msg, file=sys.stdout, flush=True)


# ═══════════════════════════════════════════════════
# ERROR TAXONOMY (P5)
# ═══════════════════════════════════════════════════

class ErrorCode(Enum):
    SYNTAX = "E100"       # Syntax error in generated code
    IMPORT = "E101"       # Missing import/dependency
    RUNTIME = "E102"      # Runtime exception during test
    FILE_NOT_FOUND = "E200"   # File path doesn't exist
    PERMISSION = "E201"   # Cannot write to path
    MALFORMED = "E300"    # LLM output not parseable (no ``` blocks)
    TRUNCATED = "E301"    # LLM output cut mid-block
    TIMEOUT = "E400"      # Agent timed out
    RESOURCE = "E401"     # Resource limit exceeded (OOM, CPU)
    REFUSAL = "E402"      # LLM refused to generate code
    GIT_CONFLICT = "E500" # Git merge conflict
    TOO_SHORT = "E302"    # Generated file too short (< 200 bytes for code)
    PLACEHOLDER = "E303"  # File contains placeholder markers (TODO, ...код...)
    UNKNOWN = "E900"      # Catch-all

ERROR_STRATEGIES = {
    ErrorCode.SYNTAX:     {"retry": True, "action": "fix_code", "agent": "developer"},
    ErrorCode.IMPORT:     {"retry": True, "action": "fix_import", "agent": "developer"},
    ErrorCode.RUNTIME:    {"retry": True, "action": "debug", "agent": "developer"},
    ErrorCode.FILE_NOT_FOUND: {"retry": True, "action": "create_path", "agent": "orchestrator"},
    ErrorCode.PERMISSION: {"retry": False, "action": "use_temp", "agent": None},
    ErrorCode.MALFORMED:  {"retry": True, "action": "requery", "agent": "orchestrator"},
    ErrorCode.TRUNCATED:  {"retry": True, "action": "split_and_retry", "agent": "orchestrator"},
    ErrorCode.TIMEOUT:    {"retry": True, "action": "split_task", "agent": "orchestrator"},
    ErrorCode.RESOURCE:   {"retry": False, "action": "throttle", "agent": None},
    ErrorCode.REFUSAL:    {"retry": True, "action": "rephrase_prompt", "agent": "orchestrator"},
    ErrorCode.GIT_CONFLICT: {"retry": False, "action": "manual_resolve", "agent": None},
    ErrorCode.TOO_SHORT:   {"retry": True, "action": "regenerate", "agent": "developer"},
    ErrorCode.PLACEHOLDER: {"retry": True, "action": "regenerate_no_placeholders", "agent": "developer"},
    ErrorCode.UNKNOWN:    {"retry": False, "action": "log_and_escalate", "agent": "mentor"},
}


def classify_error(error_text: str, raw_output: str = "") -> ErrorCode:
    """Classify error text into ErrorCode."""
    lower = (error_text + "\n" + raw_output[:2000]).lower()
    
    if "syntaxerror" in lower or "parseerror" in lower or "syntax error" in lower:
        return ErrorCode.SYNTAX
    if "modulenotfound" in lower or "importerror" in lower or "cannot find module" in lower:
        return ErrorCode.IMPORT
    if "refused" in lower or "cannot" in lower or "i can't" in lower or "apologize" in lower or "unable to" in lower:
        return ErrorCode.REFUSAL
    if "timeout" in lower or "timed out" in lower:
        return ErrorCode.TIMEOUT
    if "permission" in lower or "eacces" in lower:
        return ErrorCode.PERMISSION
    if "filenotfound" in lower or "no such file" in lower:
        return ErrorCode.FILE_NOT_FOUND
    if "out of memory" in lower or "oom" in lower or "memoryerror" in lower:
        return ErrorCode.RESOURCE
    # Check for truncation first: code block started but no closing ```
    if "```" in raw_output:
        open_blocks = raw_output.count("```") % 2
        if open_blocks == 1 and len(raw_output) > 15:
            return ErrorCode.TRUNCATED
    if len(raw_output) < 100 and not error_text:
        return ErrorCode.MALFORMED
    return ErrorCode.UNKNOWN


# ═══════════════════════════════════════════════════
# STATE DAG (P1)
# ═══════════════════════════════════════════════════

class NodeType(Enum):
    ANALYZE = "analyze"
    DESIGN = "design"
    IMPLEMENT = "implement"
    REVIEW = "review"
    FIX = "fix"
    DEPLOY = "deploy"
    DONE = "done"
    ERROR = "error"


# ═══════════════════════════════════════════════════
# RETRO — самонавчання, обмін скілами, Discovery
# ═══════════════════════════════════════════════════

RETRO_SKILLS_DIR = ".skva/skills"
RETRO_DATA_DIR = ".skva/retro"
RETRO_BUDGET_RATIO = 0.10
SKILL_REGISTRY = ".skva/skills/registry.yaml"
SKILL_SOURCES = ["Fil-m/hermes-skva"]


@dataclass
class RetroRecord:
    run_id: str
    source: str = "auto"
    skill_name: str = ""
    skill_content: str = ""
    error_pattern: str = ""
    error_action: str = ""
    tokens_spent: int = 0
    created_at: float = 0.0


def retro_budget(report: RunReport) -> int:
    total = sum(r.total_tokens for r in report.records) or 10000
    return max(1000, int(total * RETRO_BUDGET_RATIO))


async def run_retro(report: RunReport, project_dir: str) -> RetroRecord:
    budget = retro_budget(report)
    total_tok = sum(r.total_tokens for r in report.records)
    log(f"🔄 Retro: {budget} tok budget (10% of {total_tok})")
    lines = []
    for rec in report.records:
        s = "success" if rec.status == "success" else "failed"
        lines.append(f"- {rec.role} [{s}] {rec.duration:.0f}s, {rec.files_written} files, {rec.total_tokens} tok"
                     + (f", err={rec.error_code}: {rec.error_message[:60]}" if rec.error_code else ""))
    prompt = f"""Analyze this SKVA execution. Find 1-3 improvements.

RUN:
{' '.join(lines)}

Output YAML:
```yaml
errors:
  - pattern: "..."
    action: "..."
skills:
  - name: "..."
    content: "---\\nname: ...\\ndescription: ...\\n---\\n..."
prompts:
  - node: "..."
    improvement: "..."
```"""
    response, in_tok, out_tok = await gonka_call(prompt, timeout=60)
    rec = RetroRecord(run_id=str(int(time.time())), source="auto",
                      tokens_spent=in_tok + out_tok, created_at=time.time())
    if not response:
        log("Retro: no response", "WARN")
        return rec
    m = re.search(r"name:\s*[\"']?(.+?)[\"']?\n\s*content:\s*[\"']?(.+?)(?:\n\s*\w+:|$)", response, re.DOTALL)
    if m: rec.skill_name, rec.skill_content = m.group(1).strip(), m.group(2).strip()
    m = re.search(r"pattern:\s*[\"']?(.+?)[\"']?\n\s*action:\s*[\"']?(.+?)[\"']?", response, re.DOTALL)
    if m: rec.error_pattern, rec.error_action = m.group(1).strip(), m.group(2).strip()

    retro_dir = Path(project_dir) / RETRO_DATA_DIR
    retro_dir.mkdir(parents=True, exist_ok=True)
    (retro_dir / f"{rec.run_id}.yaml").write_text(f"run_id: {rec.run_id}\nsource: {rec.source}\ntokens: {rec.tokens_spent}\nresponse: |\n  {response.replace(chr(10), chr(10)+'  ')}\n")

    if rec.skill_name and rec.skill_content:
        sd = Path(project_dir) / RETRO_SKILLS_DIR
        sd.mkdir(parents=True, exist_ok=True)
        (sd / f"{rec.skill_name.lower().replace(' ', '-')}.md").write_text(rec.skill_content)
        log(f"Retro: skill '{rec.skill_name}' saved")
    if rec.error_pattern:
        log(f"Retro: new error pattern '{rec.error_pattern[:60]}' → {rec.error_action[:60]}")
    c = _gonka_estimate_cost(in_tok, out_tok)
    log(f"Retro: done ({in_tok}→{out_tok} tok, ~${c:.4f})")
    return rec


async def discover_skills(query: str = "", max_results: int = 10) -> list:
    results = []
    for source in SKILL_SOURCES:
        url = f"https://api.github.com/repos/{source}/contents/{RETRO_SKILLS_DIR}"
        proc = await asyncio.create_subprocess_exec("curl", "-s", url, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            for f in (json.loads(out.decode()) if isinstance(json.loads(out.decode()), list) else []):
                if f["name"].endswith(".md"):
                    results.append({"name": f["name"], "path": f["path"], "url": f["download_url"], "source": source})
    if query:
        url = f"https://api.github.com/search/code?q={query}+path:.skva/skills/&per_page={max_results}"
        proc = await asyncio.create_subprocess_exec("curl", "-s", url, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            for item in json.loads(out.decode()).get("items", []):
                results.append({"name": item["name"], "path": item["path"], "url": item["html_url"], "source": item["repository"]["full_name"]})
    return results[:max_results]


async def import_skill(url: str, project_dir: str) -> bool:
    proc = await asyncio.create_subprocess_exec("curl", "-sL", url, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    content = out.decode()
    if not content or len(content) < 50 or not content.startswith("---"):
        return False
    nm = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
    name = nm.group(1).strip() if nm else Path(url).stem
    sd = Path(project_dir) / RETRO_SKILLS_DIR
    sd.mkdir(parents=True, exist_ok=True)
    fp = sd / f"{name.lower().replace(' ', '-')}.md"
    if "<!-- imported from:" not in content:
        content += f"\n<!-- imported from: {url} -->\n"
    fp.write_text(content)
    log(f"Imported skill '{name}'")
    return True


def list_skills(project_dir: str) -> list:
    sd = Path(project_dir) / RETRO_SKILLS_DIR
    if not sd.exists():
        return []
    r = []
    for f in sorted(sd.glob("*.md")):
        c = f.read_text()
        nm = re.search(r"^name:\s*(.+)$", c, re.MULTILINE)
        ds = re.search(r"^description:\s*(.+)$", c, re.MULTILINE)
        r.append({"name": nm.group(1).strip() if nm else f.stem, "file": str(f), "desc": ds.group(1).strip() if ds else "", "size": len(c)})
    return r

@dataclass
class Node:
    id: str
    type: NodeType
    role: str              # Hermes agent role (or "system" for built-in)
    system_prompt: str = "Ти — AI асистент."
    task_template: str = ""  # Prompt template with {request} placeholder
    model: str = ""        # Model override: "" = default, "qwen3-235b", "deepseek-v4", etc.
    config: Dict = field(default_factory=dict)
    on_success: List[str] = field(default_factory=list)
    on_failure: List[str] = field(default_factory=list)
    interruptible: bool = True


class StateMachine:
    """
    DAG-based orchestration engine.
    State persisted to .skva/state.json (no server needed).
    """
    def __init__(self, project_dir: str):
        self.project_dir = Path(project_dir)
        self.state_dir = self.project_dir / SKVA_DIR
        self.state_file = self.state_dir / "state.json"
        self.nodes: Dict[str, Node] = {}
        self.current: Optional[str] = None
        self.history: List[Dict] = []
        self.results: Dict[str, Dict] = {}
        self.load()

    def add_node(self, node: Node):
        self.nodes[node.id] = node
        self.save()

    def add_edge(self, from_id: str, to_id: str, condition: str = "success"):
        """Add transition edge. condition: 'success' or 'failure'."""
        if from_id not in self.nodes:
            raise KeyError(f"Node '{from_id}' not found")
        if to_id not in self.nodes:
            raise KeyError(f"Node '{to_id}' not found")
        target_list = self.nodes[from_id].on_success if condition == "success" \
                       else self.nodes[from_id].on_failure
        if to_id not in target_list:
            target_list.append(to_id)
        self.save()

    def transition(self, node_id: str, status: str = "success") -> Optional[str]:
        """Move from node_id to next node based on status."""
        node = self.nodes.get(node_id)
        if not node:
            return None
        
        candidates = node.on_success if status == "success" else node.on_failure
        next_id = candidates[0] if candidates else None
        
        entry = {"from": node_id, "to": next_id, "status": status, "time": time.time()}
        self.history.append(entry)
        self.current = next_id
        self.save()
        return next_id

    def get_path(self) -> List[str]:
        """Return visited node sequence."""
        return [step["to"] for step in self.history if step["to"]]

    def save_state_result(self, node_id: str, success: bool, summary: str, 
                          error_code: Optional[ErrorCode] = None, files: Dict = None):
        self.results[node_id] = {
            "success": success,
            "summary": summary,
            "error_code": error_code.value if error_code else None,
            "files": list(files.keys()) if files else [],
            "time": time.time()
        }
        self.save()

    def reset(self):
        """Reset state machine for new run."""
        self.current = None
        self.history = []
        self.results = {}
        self.save()

    def save(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "current": self.current,
            "history": self.history,
            "results": self.results,
            "nodes": {
                k: {
                    "type": n.type.value,
                    "role": n.role,
                    "system_prompt": n.system_prompt,
                    "task_template": n.task_template,
                    "config": n.config,
                    "on_success": n.on_success,
                    "on_failure": n.on_failure,
                    "interruptible": n.interruptible,
                    "model": n.model
                } for k, n in self.nodes.items()
            }
        }
        with open(self.state_file, 'w') as f:
            json.dump(data, f, indent=2)

    def load(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file) as f:
                data = json.load(f)
            self.current = data.get("current")
            self.history = data.get("history", [])
            self.results = data.get("results", {})
            for k, v in data.get("nodes", {}).items():
                self.nodes[k] = Node(
                    id=k,
                    type=NodeType(v["type"]),
                    role=v.get("role", ""),
                    system_prompt=v.get("system_prompt", "Ти — AI асистент."),
                    task_template=v.get("task_template", ""),
                    config=v.get("config", {}),
                    on_success=v.get("on_success", []),
                    on_failure=v.get("on_failure", []),
                    interruptible=v.get("interruptible", True),
                    model=v.get("model", "")
                )
        except (json.JSONDecodeError, KeyError) as e:
            log(f"⚠️ Corrupted state file: {e}", "WARN")


# ═══════════════════════════════════════════════════
# DIFFS POLICY (P2)
# ═══════════════════════════════════════════════════

def should_patch(old_content: str, new_content: str) -> bool:
    """Decide whether to apply as diff or full rewrite."""
    if not old_content or not old_content.strip():
        return False  # New file → full write
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()
    change_ratio = abs(len(new_lines) - len(old_lines)) / max(len(old_lines), 1)
    return len(old_lines) < 200 and change_ratio < 0.3


def apply_search_replace(content: str, search_replace_blocks: List[tuple]) -> tuple:
    """
    Apply SEARCH/REPLACE blocks à la Aider.
    Each block: (SEARCH_text, REPLACE_text)
    Returns (patched_content, success). If any block fails to match,
    success=False and original content is returned.
    """
    result = content
    for search, replace in search_replace_blocks:
        applied = False
        if search in result:
            result = result.replace(search, replace, 1)
            applied = True
        else:
            # Fuzzy fallback: try stripped version
            search_stripped = search.strip()
            if search_stripped in result:
                result = result.replace(search_stripped, replace.strip(), 1)
                applied = True
        if not applied:
            log(f"  ⚠️ SEARCH block not found in file: {search[:60]}...", "WARN")
            return content, False
    return result, True


def parse_search_replace_blocks(text: str) -> List[tuple]:
    """
    Parse SEARCH/REPLACE blocks from agent output.
    Format:
    <<<<<<< SEARCH
    old code
    =======
    new code
    >>>>>>> REPLACE
    """
    blocks = []
    pattern = r'<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE'
    for match in re.finditer(pattern, text, re.DOTALL):
        blocks.append((match.group(1), match.group(2)))
    return blocks


# ═══════════════════════════════════════════════════
# RESOURCE BALANCER (P4)
# ═══════════════════════════════════════════════════

class ResourceManager:
    """Dynamic agent capacity based on system resources."""
    def __init__(self, project_dir: str, max_agents_cap: int = 8):
        self.project_dir = Path(project_dir)
        self.history_file = self.project_dir / SKVA_DIR / "load.json"
        self.load_history: List[Dict] = []
        self.max_cap = max_agents_cap
        self.load()

    def get_max_concurrent(self) -> int:
        """Calculate how many agents can run in parallel."""
        try:
            cpu_count = os.cpu_count() or 4
            cpu_limit = max(1, cpu_count - 1)
            
            # Try psutil, fallback to simple estimate
            ram_limit = 4  # default
            try:
                import psutil
                avail_gb = psutil.virtual_memory().available / (1024**3)
                ram_limit = max(1, int(avail_gb / 1.5))
            except ImportError:
                # Try /proc/meminfo on Linux (no psutil)
                try:
                    with open("/proc/meminfo") as f:
                        for line in f:
                            if line.startswith("MemAvailable:"):
                                parts = line.split()
                                avail_kb = int(parts[1])
                                ram_limit = max(1, int(avail_kb / (1.5 * 1024 * 1024)))
                                break
                except (FileNotFoundError, OSError, IndexError, ValueError):
                    # Fallback: assume 4GB available → 2 agents
                    ram_limit = 2
            
            result = min(cpu_limit, ram_limit, self.max_cap)
            
            # Reduce if recent OOMs
            recent = [e for e in self.load_history[-10:] 
                     if e.get("event") == "oom"]
            if len(recent) >= 2:
                result = max(1, result - 1)
            
            return result
        except Exception:
            return 1  # Safe fallback

    def update(self, active_agents: int, event: str = "tick"):
        self.load_history.append({
            "time": time.time(),
            "active": active_agents,
            "event": event
        })
        self.load_history = self.load_history[-100:]
        self.save()

    def save(self):
        (self.project_dir / SKVA_DIR).mkdir(parents=True, exist_ok=True)
        with open(self.history_file, 'w') as f:
            json.dump(self.load_history, f)

    def load(self):
        if self.history_file.exists():
            try:
                with open(self.history_file) as f:
                    self.load_history = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.load_history = []


# ═══════════════════════════════════════════════════
# ISOLATION (P3)
# ═══════════════════════════════════════════════════

class SecureWorkspace:
    """Isolated temp workspace for agent code execution."""
    def __init__(self, prefix="skva_agent_"):
        self.temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        self.temp_dir.chmod(0o700)
        for sub in ["input", "output", "work"]:
            (self.temp_dir / sub).mkdir()
            (self.temp_dir / sub).chmod(0o700)
        self._created = True

    def seed_from_project(self, project_dir: str):
        """Copy project files into work_dir as input context for the agent.
        Skips binary files, node_modules, .git, __pycache__ etc."""
        src = Path(project_dir)
        if not src.exists():
            log(f"  seed: project dir {project_dir} does not exist, skipping", "WARN")
            return
        count = 0
        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            if _is_binary(f):
                continue
            rel = f.relative_to(src)
            if any(skip in rel.parts for skip in SKIP_DIRS):
                continue
            try:
                dst = self.work_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                count += 1
            except (OSError, PermissionError):
                continue
        log(f"  seeded {count} files into workspace work_dir")

    @property
    def work_dir(self) -> Path:
        return self.temp_dir / "work"

    @property
    def input_dir(self) -> Path:
        return self.temp_dir / "input"

    @property
    def output_dir(self) -> Path:
        return self.temp_dir / "output"

    def cleanup(self):
        if self._created and self.temp_dir.exists():
            shutil.rmtree(str(self.temp_dir), ignore_errors=True)
            self._created = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()


def limit_resources():
    """Resource limits for subprocess execution (Unix)."""
    try:
        import resource
        # 1.5GB memory limit per agent
        resource.setrlimit(resource.RLIMIT_AS, (int(1.5e9), int(1.5e9)))
        # 100MB file size limit
        resource.setrlimit(resource.RLIMIT_FSIZE, (100*1024*1024, 100*1024*1024))
    except (ImportError, ValueError, resource.error):
        pass  # Not on Unix or already configured


# ═══════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════

def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", file=sys.stderr, flush=True)

def count_tokens(text):
    return len(text) // 4


# ═══════════════════════════════════════════════════
# MARKDOWN PARSER (truncation-safe)
# ═══════════════════════════════════════════════════

def _parse_filepath_blocks(text):
    """Parse // filepath: from markdown code blocks. Handles truncation."""
    files = {}
    blocks = re.findall(r'```(?:\w+)?\n(.*?)```', text, re.DOTALL)
    for block in blocks:
        _extract_filepath(block, files)
    # Truncation fallback
    lines = text.split('\n')
    found_fence = False
    block_content = []
    for line in lines:
        if line.startswith('```') and not found_fence:
            found_fence = True; block_content = []; continue
        elif line.startswith('```') and found_fence:
            found_fence = False; block_content = []; continue
        if found_fence: block_content.append(line)
    if found_fence and block_content:
        remaining = '\n'.join(block_content)
        if re.search(r'(?://|#|<!--)\s*filepath:\s*\S+', remaining):
            _extract_filepath(remaining, files)
    return files


def _extract_filepath(block, files_dict):
    match = re.search(r'(?://|#|<!--)\s*filepath:\s*([^\n]+)', block)
    if match:
        path = match.group(1).strip()
        start = block.find(match.group(0)) + len(match.group(0))
        content = block[start:].strip()
        if content.endswith('```'): content = content[:-3].strip()
        files_dict[path] = content


def _parse_no_fence_filepath(text):
    files = {}
    lines = text.split('\n')
    current_path = None; current_content = []
    for line in lines:
        fp = re.match(r'\s*(?://|#|<!--)\s*filepath:\s*(\S+)', line)
        if fp:
            if current_path and current_content:
                files[current_path] = '\n'.join(current_content)
            current_path = fp.group(1).strip(); current_content = []
        elif current_path:
            current_content.append(line)
    if current_path and current_content:
        files[current_path] = '\n'.join(current_content)
    return files


# ═══════════════════════════════════════════════════
# AGENT CORE
# ═══════════════════════════════════════════════════

BINARY_EXTENSIONS = frozenset({
    '.png','.jpg','.jpeg','.gif','.bmp','.ico','.webp',
    '.zip','.tar','.gz','.bz2','.xz','.7z','.rar',
    '.pdf','.doc','.docx','.xls','.xlsx','.ppt','.pptx',
    '.woff','.woff2','.ttf','.eot','.otf',
    '.mp3','.mp4','.avi','.mov','.wav','.ogg',
    '.pyc','.pyo','.pyd','.so','.dll','.dylib',
    '.exe','.msi','.bin','.o','.a','.lib',
})
SKIP_DIRS = frozenset({'node_modules','.git','__pycache__','.venv','venv','dist','build','.next','.turbo','target'})

def _is_binary(path):
    return Path(path).suffix.lower() in BINARY_EXTENSIONS


# ═══════════════════════════════════════════════════
# GonkaClient — прямий API запит до Gonka
# ═══════════════════════════════════════════════════

GONKA_API = "https://proxy.gonka.gg/v1/chat/completions"
GONKA_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8"
GONKA_PRICE_IN = 0.20   # $/M tokens input
GONKA_PRICE_OUT = 0.30  # $/M tokens output

def _load_gonka_key() -> str:
    """Load Gonka API key from env or ~/.hermes/.env"""
    key = os.environ.get("GONKA_API_KEY", "")
    if key:
        return key
    env_path = os.path.expanduser("~/.hermes/.env")
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip().strip("export ")
                if line.startswith("GONKA_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

def _gonka_estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * GONKA_PRICE_IN + output_tokens * GONKA_PRICE_OUT) / 1_000_000

async def gonka_call(prompt: str, timeout: int = 300) -> tuple:
    """
    Call Gonka API directly. Returns (response_text, input_tokens, output_tokens).
    Handles 429 with exponential backoff (1s, 2s, 4s, 8s).
    Returns ("", 0, 0) on failure.
    """
    key = _load_gonka_key()
    if not key:
        log("GONKA_API_KEY not found", "ERROR")
        return "", 0, 0

    data = json.dumps({
        "model": GONKA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192,
        "temperature": 0.2,
    })

    # Write data to temp file to avoid "Argument list too long"
    import tempfile as _tf
    data_dir = _tf.mkdtemp(prefix="skva_gonka_")
    data_file = Path(data_dir) / "data.json"
    data_file.write_text(data)
    data_arg = f"@{data_file}"
    _cleanup = lambda: shutil.rmtree(data_dir, ignore_errors=True)

    for attempt in range(4):  # 0, 1, 2, 3 with 1,2,4,8s backoff
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "--max-time", str(timeout),
                "-X", "POST", GONKA_API,
                "-H", "Content-Type: application/json",
                "-H", f"Authorization: Bearer {key}",
                "-d", data_arg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout + 10
            )
        except asyncio.TimeoutError:
            try: proc.kill()
            except: pass
            log(f"Gonka timeout (attempt {attempt+1}/4)", "WARN")
            await asyncio.sleep(2 ** attempt)
            continue

        if proc.returncode != 0:
            log(f"Gonka curl exit {proc.returncode} (attempt {attempt+1}/4)", "WARN")
            await asyncio.sleep(2 ** attempt)
            continue

        try:
            result = json.loads(stdout.decode())
        except json.JSONDecodeError:
            log(f"Gonka bad JSON (attempt {attempt+1}/4)", "WARN")
            await asyncio.sleep(2 ** attempt)
            continue

        if "error" in result:
            err = result["error"]
            err_str = json.dumps(err)[:200]
            if "429" in err_str:
                wait = 2 ** attempt
                log(f"Gonka 429 rate limit, waiting {wait}s...", "WARN")
                await asyncio.sleep(wait)
                continue
            log(f"Gonka API error: {err_str}", "ERROR")
            return "", 0, 0

        if "choices" not in result:
            log(f"Gonka unexpected response: {str(result)[:200]}", "ERROR")
            return "", 0, 0

        content = result["choices"][0]["message"]["content"]
        usage = result.get("usage", {})
        in_tok = usage.get("prompt_tokens", count_tokens(prompt))
        out_tok = usage.get("completion_tokens", count_tokens(content))
        cost = _gonka_estimate_cost(in_tok, out_tok)
        log(f"Gonka OK: {in_tok}→{out_tok} tok, ~${cost:.6f}")
        _cleanup()
        return content, in_tok, out_tok

    log("Gonka all 4 attempts failed", "ERROR")
    _cleanup()
    return "", 0, 0


def is_gonka_model(model: str) -> bool:
    """Check if model string refers to Gonka."""
    return model and ("qwen" in model.lower() or "gonka" in model.lower())


def load_phase_context(project_dir, phase, max_chars=12000):
    phase_dir = Path(project_dir) / ".hermes" / "artifacts" / phase
    if not phase_dir.exists():
        return ""
    parts = []; total = 0
    for f in sorted(phase_dir.rglob("*")):
        if not f.is_file() or _is_binary(f) or f.stat().st_size == 0:
            continue
        rel = str(f.relative_to(phase_dir))
        if any(skip in rel.split(os.sep) for skip in SKIP_DIRS):
            continue
        remaining = max_chars - total
        if remaining <= 0: break
        try:
            text = f.read_text(errors='replace')[:remaining]
        except (UnicodeDecodeError, PermissionError, OSError):
            continue
        parts.append(f"--- {rel} ---\n{text}")
        total += len(text)
    return "\n\n".join(parts)


CODE_EXTENSIONS = frozenset({'.py','.js','.ts','.jsx','.tsx','.html','.css','.java',
                             '.go','.rs','.rb','.php','.c','.cpp','.h','.hpp','.swift',
                             '.kt','.scala','.sh','.bash','.yaml','.yml','.toml','.sql'})

PLACEHOLDER_PATTERNS = re.compile(
    r'(?:TODO|FIXME|XXX)\s*:|\.\.\.\s*код\s*\.\.\.|\.\.\.\s*code\s*\.\.\.|'
    r'решта\s*коду\s*без\s*змін|rest\s*of\s*the\s*code|'
    r'//\s*\.\.\.|#\s*\.\.\.|<!--\s*\.\.\.|'
    r'повторити\s*логіку|same\s*logic\s*as\s*above',
    re.IGNORECASE
)

def _validate_files(files: Dict[str, str]) -> Optional[ErrorCode]:
    """Quality gate: validate generated files. Returns ErrorCode if gate fails."""
    for path, content in files.items():
        ext = Path(path).suffix.lower()
        is_code = ext in CODE_EXTENSIONS or ext == ''
        
        # Gate 1: file too short for code
        if is_code and len(content) < 200 and ext != '.gitignore':
            log(f"  ⚠️ Quality gate FAIL: {path} too short ({len(content)} bytes)", "WARN")
            return ErrorCode.TOO_SHORT
        
        # Gate 2: placeholder markers
        if is_code and PLACEHOLDER_PATTERNS.search(content):
            log(f"  ⚠️ Quality gate FAIL: {path} contains placeholder markers", "WARN")
            return ErrorCode.PLACEHOLDER
    
    return None


class MarkdownAgent:
    """
    Agent that uses markdown code blocks with // filepath:.
    v5: returns structured result with ErrorCode.
    """
    def __init__(self, role, system_prompt, task_prompt, project_dir, 
                 timeout=300, previous_code="", previous_error="",
                 secure_workspace: Optional[SecureWorkspace] = None,
                 model: str = ""):
        self.role = role
        self.project_dir = Path(project_dir)
        self.timeout = timeout
        self.success = False
        self.error = ""
        self.error_code: Optional[ErrorCode] = None
        self.files = {}
        self.summary = ""
        self.raw_output = ""
        self.secure_workspace = secure_workspace
        self.model = model
        self.run_duration = 0.0
        self.input_tokens = 0
        self.output_tokens = 0

        # Token-aware retry context
        retry_context = ""
        if previous_code:
            pc_tokens = count_tokens(previous_code)
            budget = min(TOKEN_LIMIT, 3000)
            truncated_code = previous_code[-budget*4:] if pc_tokens > budget else previous_code
            retry_context = f"""
Попередня версія коду (має помилку):
{truncated_code}

Помилка:
{previous_error}

ВИПРАВ ЦЕЙ КОД. Не генеруй наново — виправ конкретну помилку.
"""

        work_dir = secure_workspace.work_dir if secure_workspace else \
            self.project_dir / ".hermes" / "artifacts" / role

        self.full_prompt = f"""{system_prompt}

Твоя роль: {role}.
Проект: {self.project_dir}
Робоча директорія: {work_dir}

Завдання:
{task_prompt}

{retry_context}

ВАЖЛИВО — формат відповіді:

Для КОЖНОГО файлу обов'язково вказуй filepath на початку блоку:

```language
// filepath: шлях/до/твого/файлу.extension
... код ...
```

Якщо це РЕДАГУВАННЯ існуючого файлу, використовуй SEARCH/REPLACE ВСЕРЕДИНІ блоку:

```language
// filepath: шлях/до/файлу.extension
<<<<<<< SEARCH
старий код
=======
новий код
>>>>>>> REPLACE
```

ВАЖЛИВО: filepath має БУТИ РЕАЛЬНИМ шляхом у проекті, а не прикладом.
Не копіюй приклад — пиши шлях до файлу який реально створюєш."""

    async def run(self):
        log(f"Starting {self.role} (timeout={self.timeout}s)")
        start = time.time()
        
        work_dir = self.secure_workspace.work_dir if self.secure_workspace \
            else self.project_dir / ".hermes" / "artifacts" / self.role
        work_dir.mkdir(parents=True, exist_ok=True)

        # Build env with optional model override
        env = {**os.environ, "HERMES_HOME": HERMES_HOME,
               "SKVA_WORK_DIR": str(work_dir)}
        if self.model:
            env["HERMES_INFERENCE_MODEL"] = self.model
            log(f"  model: {self.model}")

        use_gonka = is_gonka_model(self.model)

        if use_gonka:
            # Call Gonka API directly (cheaper, faster for complex tasks)
            log(f"  → Gonka {GONKA_MODEL}")
            response, in_tok, out_tok = await gonka_call(
                self.full_prompt, timeout=self.timeout
            )
            self.raw_output = response
            self.input_tokens = in_tok
            self.output_tokens = out_tok
            log(f"  Gonka done: {len(response)} chars, {in_tok}→{out_tok} tok")
        else:
            # Call Hermes CLI (default model)
            proc = await asyncio.create_subprocess_exec(
                "hermes", "chat", "-q", self.full_prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=limit_resources if sys.platform != "win32" else None,
                env=env
            )

            output_lines = []
            try:
                while True:
                    try:
                        line = await asyncio.wait_for(proc.stdout.readline(), timeout=self.timeout)
                    except asyncio.TimeoutError:
                        proc.kill()
                        self.error = "timeout"
                        self.error_code = ErrorCode.TIMEOUT
                        break
                    if not line:
                        break
                    output_lines.append(line.decode(errors='replace'))
                self.raw_output = "".join(output_lines)
                await proc.stderr.read()
            except Exception as e:
                proc.kill()
                self.error = str(e)
                self.raw_output = "".join(output_lines)

        elapsed = time.time() - start
        self.run_duration = elapsed
        self.input_tokens = count_tokens(self.full_prompt)
        self.output_tokens = count_tokens(self.raw_output)

        # Parse output
        self.files = _parse_filepath_blocks(self.raw_output)
        if not self.files:
            self.files = _parse_no_fence_filepath(self.raw_output)

        # Also parse SEARCH/REPLACE blocks
        sr_blocks = parse_search_replace_blocks(self.raw_output)

        if self.files:
            # Write new files or apply SEARCH/REPLACE patches
            count = 0
            written_paths = []
            patch_count = 0
            for path, content in self.files.items():
                # For existence check: use work_dir (where project was seeded)
                check_path = self.project_dir / path if not self.secure_workspace \
                    else self.secure_workspace.work_dir / path
                # For writing output: use output_dir
                full_path = self.project_dir / path if not self.secure_workspace \
                    else self.secure_workspace.output_dir / path
                full_path.parent.mkdir(parents=True, exist_ok=True)

                # Detect SEARCH/REPLACE blocks inside this file's content
                inner_sr = parse_search_replace_blocks(content)
                if inner_sr and check_path.exists():
                    # Apply as patch to existing file (from work_dir context)
                    old_content = check_path.read_text()
                    patched, patch_ok = apply_search_replace(old_content, inner_sr)
                    if not patch_ok:
                        log(f"  ⚠️ Patch failed for {path}, retrying with full rewrite", "WARN")
                        self.error = f"Patch not applied: SEARCH block not found"
                        self.error_code = ErrorCode.MALFORMED
                        break  # Stop processing — retry via auto_fix
                    full_path.write_text(patched)
                    patch_count += len(inner_sr)
                    written_paths.append(f"{path} (patch)")
                elif inner_sr and not check_path.exists():
                    # File doesn't exist yet — extract REPLACE content
                    replace_only = "\n\n".join(b[1] for b in inner_sr)
                    full_path.write_text(replace_only)
                    count += 1
                    written_paths.append(f"{path} (new from patch)")
                else:
                    # Normal full rewrite
                    full_path.write_text(content)
                    count += 1
                    written_paths.append(str(path))
            # Quality Gate: validate files before declaring success
            gate_error = _validate_files(self.files)
            if gate_error:
                self.success = False
                self.error = f"Quality gate failed: {gate_error.value}"
                self.error_code = gate_error
                log(f"❌ {self.role} ({elapsed:.0f}s): {self.error}", "ERROR")
            elif self.error_code:
                # Error set during file processing (e.g. patch failure) — don't overwrite
                self.success = False
                log(f"❌ {self.role} ({elapsed:.0f}s): {self.error}", "ERROR")
            else:
                self.success = True
                log(f"✅ {self.role} ({elapsed:.0f}s) — {count} files, {patch_count} patches")
                for p in written_paths[:3]:
                    log(f"  📄 {p}")
        else:
            lower = self.raw_output.lower()
            if any(p in lower for p in ["i cannot", "i can't", "apologize", "unable to"]):
                self.error = "LLM refused"
                self.error_code = ErrorCode.REFUSAL
            elif len(self.raw_output) < 50:
                self.error = "empty response"
                self.error_code = ErrorCode.MALFORMED
            else:
                self.error = "no // filepath: blocks or SEARCH/REPLACE found"
                self.error_code = ErrorCode.MALFORMED
                debug_path = self.project_dir / ".hermes" / "artifacts" / self.role / "_raw_output.txt"
                debug_path.write_text(self.raw_output[:10000])
            log(f"❌ {self.role} ({elapsed:.0f}s): {self.error} [{self.error_code}]", "ERROR")

        return self


def _build_retry_context(files_dict, error_msg, budget=4000):
    """Token-aware retry context builder."""
    if not files_dict:
        return error_msg
    sorted_files = sorted(files_dict.items(), key=lambda x: len(x[1]))
    parts = []; total = 0
    for path, content in sorted_files:
        available = min(len(content), MAX_FILE_CHARS)
        remaining = budget * 4 - total
        if remaining <= 0: break
        chunk = content[:min(available, remaining)]
        parts.append(f"=== {path} ===\n{chunk}")
        total += len(chunk)
    code_block = "\n\n".join(parts)
    return f"{code_block}\n\nПомилка:\n{error_msg}" if error_msg else code_block


async def auto_fix(role, task_prompt, project_dir, max_retries=3,
                   secure_workspace=None, model=""):
    """Auto-fix with error taxonomy and retry strategies."""
    previous_code = ""
    previous_error = ""
    report = get_report()
    
    for attempt in range(1, max_retries + 1):
        log(f"  {role} attempt {attempt}/{max_retries}")
        
        # Report: start agent
        rec = None
        if report:
            rec = report.start_agent("", role, model, attempt, max_retries)

        agent = MarkdownAgent(
            role, "Ти — Developer. Пиши код.",
            task_prompt, project_dir, timeout=300,
            previous_code=previous_code, previous_error=previous_error,
            secure_workspace=secure_workspace,
            model=model
        )
        await agent.run()

        if agent.success:
            if report and rec:
                report.complete_agent(rec, "success", agent.run_duration,
                    files=len(agent.files),
                    patches=0,
                    input_tokens=agent.input_tokens,
                    output_tokens=agent.output_tokens,
                    error_code=agent.error_code.value if agent.error_code else "",
                    error_msg=agent.error)
            return agent

        ec = agent.error_code or classify_error(agent.error, agent.raw_output)
        if report and rec:
            report.complete_agent(rec, "failed", agent.run_duration,
                input_tokens=agent.input_tokens,
                output_tokens=agent.output_tokens,
                error_code=ec.value,
                error_msg=agent.error)

        strategy = ERROR_STRATEGIES.get(ec, ERROR_STRATEGIES[ErrorCode.UNKNOWN])
        
        if not strategy["retry"]:
            log(f"  ❌ Non-retryable error {ec.value}, giving up")
            return agent

        if attempt < max_retries:
            log(f"  🔄 Retryable {ec.value}, strategy={strategy['action']}")
            previous_code = ""
            if agent.files:
                previous_code = _build_retry_context(agent.files, agent.error)
            previous_error = f"[{ec.value}] {agent.error}"

    return agent


# ═══════════════════════════════════════════════════
# WORKFLOW ENGINE (DAG-based)
# ═══════════════════════════════════════════════════

async def run_node(node: Node, sm: StateMachine, request: str, 
                   project_dir: str, resources: ResourceManager) -> bool:
    """Execute a single DAG node and transition."""
    log(f"🏗 DAG node: {node.id} ({node.type.value})")
    report = get_report()
    
    task = node.task_template.format(request=request) if node.task_template else request
    context = load_phase_context(project_dir, node.id)
    if context:
        task = f"{task}\n\nКонтекст:\n{context}"

    max_parallel = resources.get_max_concurrent()
    log(f"  Capacity: {max_parallel} concurrent agents")
    if report:
        report.resource_status(max_parallel, 0)

    if node.type == NodeType.ANALYZE:
        agents = await run_parallel([
            {"role": "analyst", "system_prompt": "Ти — Systems Analyst.",
             "prompt": f"Збери вимоги для: {task}", "timeout": 300,
             "model": node.model},
        ], project_dir)
    elif node.type == NodeType.DESIGN:
        agents = await run_parallel([
            {"role": "architect", "system_prompt": "Ти — Software Architect.",
             "prompt": f"Спроектуй архітектуру для: {task}", "timeout": 300,
             "model": node.model},
        ], project_dir)
    elif node.type == NodeType.IMPLEMENT:
        with SecureWorkspace(prefix=f"skva_{node.id}_") as ws:
            ws.seed_from_project(project_dir)
            agent = await auto_fix("developer", task, project_dir,
                                   secure_workspace=ws, model=node.model)
            # Copy CLEAN files from output_dir to project
            if agent.success and agent.files:
                for path in agent.files.keys():
                    src = ws.output_dir / path
                    dst = Path(project_dir) / path
                    if src.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copy2(src, dst)
                        except shutil.SameFileError:
                            pass  # Same path, already in project
        agents = [agent]
    elif node.type == NodeType.REVIEW:
        agent = MarkdownAgent(
            "qa", "Ти — QA Engineer. Перевір код на помилки.",
            f"Проведи code review. Знайди мінімум 3 проблеми:\n{task}\n"
            f"Наприкінці напиши СТАТУС: ПОМИЛКА або СТАТУС: УСПІШНО",
            project_dir, timeout=300
        )
        await agent.run()
        agents = [agent]
    elif node.type == NodeType.FIX:
        with SecureWorkspace(prefix=f"skva_{node.id}_") as ws:
            ws.seed_from_project(project_dir)
            agent = await auto_fix("developer", f"ВИПРАВ ПОМИЛКИ:\n{task}",
                                   project_dir, max_retries=2,
                                   secure_workspace=ws, model=node.model)
            if agent.success and agent.files:
                for path in agent.files.keys():
                    src = ws.output_dir / path
                    dst = Path(project_dir) / path
                    if src.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copy2(src, dst)
                        except shutil.SameFileError:
                            pass
        agents = [agent]
    elif node.type == NodeType.DEPLOY:
        agents = await run_parallel([
            {"role": "fullstack", "system_prompt": "Ти — DevOps.",
             "prompt": f"Фіналізуй проект:\n{task}", "timeout": 300,
             "model": node.model},
        ], project_dir)
    else:
        agents = [MarkdownAgent(node.role, node.system_prompt, task, project_dir)]
        await agents[0].run()

    success = any(a.success for a in agents)
    # REVIEW node: parse QA verdict, don't trust agent.success alone
    if node.type == NodeType.REVIEW and success:
        review_raw = agents[0].raw_output.upper()
        if "СТАТУС: ПОМИЛКА" in review_raw or "STATUS: FAIL" in review_raw:
            success = False
            log(f"  🔄 QA found issues, routing to fix branch")
    errors = [a.error for a in agents if not a.success]
    error_code = None
    if errors:
        raw = "\n".join(a.raw_output for a in agents if not a.success)
        error_code = classify_error(errors[0], raw)

    # Save result
    sm.save_state_result(
        node.id, success,
        summary=errors[0] if errors else "ok",
        error_code=error_code,
        files={k: v for a in agents for k, v in a.files.items()}
    )

    # Transition
    status = "success" if success else "failure"
    next_node = sm.transition(node.id, status)
    
    if report:
        if not success and errors:
            ec = error_code.value if error_code else "UNKNOWN"
            report.phase_error(node.id, ec, errors[0])
        if next_node and next_node != node.id:
            report.start_phase(next_node, sm.nodes[next_node].type.value if next_node in sm.nodes else "?")
    
    if next_node and next_node != node.id:
        log(f"  ➡️ {node.id} → {next_node} ({status})")
        if next_node == "error":
            log(f"  ❌ Entered ERROR state")
            return False
        next_n = sm.nodes.get(next_node)
        if next_n and next_n.type != NodeType.DONE:
            return await run_node(next_n, sm, request, project_dir, resources)

    return success


async def run_dag(workflow_nodes: List[Node], edges: List[tuple],
                  request: str, project_dir: str) -> bool:
    """
    Run a custom DAG workflow.
    workflow_nodes: list of Node objects
    edges: list of (from_id, to_id, condition) tuples
    """
    project_dir = os.path.abspath(project_dir)
    sm = StateMachine(project_dir)
    sm.reset()
    
    for node in workflow_nodes:
        sm.add_node(node)
    for from_id, to_id, condition in edges:
        sm.add_edge(from_id, to_id, condition)

    resources = ResourceManager(project_dir)
    start = time.time()

    start_node = workflow_nodes[0].id if workflow_nodes else None
    if not start_node:
        log("❌ No start node in workflow", "ERROR")
        return False

    # Wrap execution in report context manager
    with RunReport(project_dir=project_dir) as report:
        report.start_phase(start_node, workflow_nodes[0].type.value)
        ok = await run_node(sm.nodes[start_node], sm, request, project_dir, resources)
        report.end_phase(start_node, "success" if ok else "failure")
        report.print_final_summary()

    # Retro: самонавчання після DAG (10% бюджету)
    retro_rec = await run_retro(report, project_dir)

    log(f"🏁 DAG done ({time.time()-start:.0f}s): {'✅' if ok else '❌'}")
    return ok


# ═══════════════════════════════════════════════════
# PREDEFINED WORKFLOWS
# ═══════════════════════════════════════════════════

def build_solo_dag() -> List[Node]:
    """Solo method as DAG: single IMPLEMENT node."""
    return [
        Node("impl", NodeType.IMPLEMENT, "fullstack",
             system_prompt="Ти — Fullstack Developer.",
             task_template="{request}",
             model="qwen3-235b",
             on_success=["done"]),
        Node("done", NodeType.DONE, "", on_success=[]),
    ]


def build_rada_dag() -> List[Node]:
    """Rada+Fabryka: ANALYZE → IMPLEMENT → DEPLOY"""
    return [
        Node("analyze", NodeType.ANALYZE, "analyst",
             task_template="{request}",
             on_success=["implement"],
             on_failure=["error"]),
        Node("implement", NodeType.IMPLEMENT, "developer",
             task_template="{request}",
             model="qwen3-235b",
             on_success=["deploy"],
             on_failure=["fix"]),
        Node("fix", NodeType.FIX, "developer",
             task_template="{request}",
             model="qwen3-235b",
             on_success=["deploy"],
             on_failure=["error"]),
        Node("deploy", NodeType.DEPLOY, "fullstack",
             task_template="{request}",
             on_success=["done"],
             on_failure=["error"]),
        Node("done", NodeType.DONE, ""),
        Node("error", NodeType.ERROR, ""),
    ]


def build_agile_dag() -> List[Node]:
    """Agile: DESIGN → IMPLEMENT → REVIEW → (FIX|DONE)"""
    return [
        Node("design", NodeType.DESIGN, "architect",
             task_template="{request}",
             on_success=["implement"],
             on_failure=["error"]),
        Node("implement", NodeType.IMPLEMENT, "developer",
             task_template="{request}",
             model="qwen3-235b",
             on_success=["review"],
             on_failure=["fix"]),
        Node("review", NodeType.REVIEW, "qa",
             task_template="{request}",
             on_success=["done"],
             on_failure=["fix"]),
        Node("fix", NodeType.FIX, "developer",
             task_template="ВИПРАВ ПОМИЛКИ:\n{request}",
             model="qwen3-235b",
             on_success=["review"],
             on_failure=["error"]),
        Node("done", NodeType.DONE, ""),
        Node("error", NodeType.ERROR, ""),
    ]


def build_pipeline_dag() -> List[Node]:
    """Pipeline: ANALYZE → DESIGN → IMPLEMENT → REVIEW → DEPLOY"""
    return [
        Node("analyze", NodeType.ANALYZE, "analyst",
             task_template="{request}",
             on_success=["design"], on_failure=["error"]),
        Node("design", NodeType.DESIGN, "architect",
             task_template="{request}",
             on_success=["implement"], on_failure=["error"]),
        Node("implement", NodeType.IMPLEMENT, "developer",
             task_template="{request}",
             model="qwen3-235b",
             on_success=["review"], on_failure=["fix"]),
        Node("review", NodeType.REVIEW, "qa",
             task_template="{request}",
             on_success=["deploy"], on_failure=["fix"]),
        Node("fix", NodeType.FIX, "developer",
             task_template="ВИПРАВ ПОМИЛКИ:\n{request}",
             model="qwen3-235b",
             on_success=["review"], on_failure=["error"]),
        Node("deploy", NodeType.DEPLOY, "fullstack",
             task_template="{request}",
             on_success=["done"], on_failure=["error"]),
        Node("done", NodeType.DONE, ""),
        Node("error", NodeType.ERROR, ""),
    ]


# ═══════════════════════════════════════════════════
# API (backward compatible)
# ═══════════════════════════════════════════════════

async def solo(request, project_dir="."):
    """Solo: one agent (uses DAG internally)."""
    project_dir = os.path.abspath(project_dir)
    dag = build_solo_dag()
    edges = [("impl", "done", "success")]
    return await run_dag(dag, edges, request, project_dir)


async def rada_fabryka(request, project_dir="."):
    """Rada+Fabryka: analysis → implement → deploy (DAG-based)."""
    project_dir = os.path.abspath(project_dir)
    dag = build_rada_dag()
    edges = [
        ("analyze", "implement", "success"),
        ("analyze", "error", "failure"),
        ("implement", "deploy", "success"),
        ("implement", "fix", "failure"),
        ("fix", "deploy", "success"),
        ("fix", "error", "failure"),
        ("deploy", "done", "success"),
        ("deploy", "error", "failure"),
    ]
    return await run_dag(dag, edges, request, project_dir)


async def agile(request, project_dir="."):
    """Agile: design → implement → review → (fix|done)."""
    project_dir = os.path.abspath(project_dir)
    dag = build_agile_dag()
    edges = [
        ("design", "implement", "success"),
        ("design", "error", "failure"),
        ("implement", "review", "success"),
        ("implement", "fix", "failure"),
        ("review", "done", "success"),
        ("review", "fix", "failure"),
        ("fix", "review", "success"),
        ("fix", "error", "failure"),
    ]
    return await run_dag(dag, edges, request, project_dir)


async def pipeline(request, project_dir="."):
    """Full pipeline: analyze → design → implement → review → deploy."""
    project_dir = os.path.abspath(project_dir)
    dag = build_pipeline_dag()
    edges = [
        ("analyze", "design", "success"),
        ("analyze", "error", "failure"),
        ("design", "implement", "success"),
        ("design", "error", "failure"),
        ("implement", "review", "success"),
        ("implement", "fix", "failure"),
        ("review", "deploy", "success"),
        ("review", "fix", "failure"),
        ("fix", "review", "success"),
        ("fix", "error", "failure"),
        ("deploy", "done", "success"),
        ("deploy", "error", "failure"),
    ]
    return await run_dag(dag, edges, request, project_dir)


async def run_parallel(configs, project_dir):
    agents = [MarkdownAgent(
        role=cfg["role"],
        system_prompt=cfg.get("system_prompt", "Ти — AI асистент."),
        task_prompt=cfg["prompt"],
        project_dir=project_dir,
        timeout=cfg.get("timeout", 300),
        model=cfg.get("model", "")
    ) for cfg in configs]
    await asyncio.gather(*[a.run() for a in agents])
    return agents


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    task = sys.argv[2] if len(sys.argv) > 2 else "create hello"
    proj = sys.argv[3] if len(sys.argv) > 3 else f"/tmp/skva-{int(time.time())}"

    if cmd == "solo":
        sys.exit(0 if asyncio.run(solo(task, proj)) else 1)
    elif cmd == "rada":
        sys.exit(0 if asyncio.run(rada_fabryka(task, proj)) else 1)
    elif cmd == "agile":
        sys.exit(0 if asyncio.run(agile(task, proj)) else 1)
    elif cmd == "pipeline":
        sys.exit(0 if asyncio.run(pipeline(task, proj)) else 1)
    else:
        print("SKVA v5 — DAG-based multi-agent orchestration")
        print()
        print("  skva solo     \"запит\"  — Solo (1 agent)")
        print("  skva rada     \"запит\"  — Rada+Fabryka (analyze→implement→deploy)")
        print("  skva agile    \"запит\"  — Agile (design→implement→review→fix)")
        print("  skva pipeline \"запит\"  — Full pipeline (+analyze, +deploy)")
        print("  skva doctor             — діагностика")
        print("  skva test               — smoke test")

if __name__ == "__main__":
    main()
