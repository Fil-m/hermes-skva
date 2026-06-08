# SKVA CLIDashboard — auto-generated
"""TZ gap closure"""
import sys, os, json, time, asyncio
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass

# ANSI color codes
COLORS = {
    "reset": "\033[0m",
    "blue": "\033[94m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "red": "\033[91m",
    "cyan": "\033[96m",
    "white": "\033[97m",
    "gray": "\033[90m",
}

ICONS = {
    "analyze": "🔍",
    "design": "🎨",
    "implement": "💻",
    "review": "👁",
    "fix": "🔧",
    "deploy": "🚀",
    "done": "✅",
    "error": "❌",
}

# Fallback log function if not imported
def log(msg: str, level: str = "INFO"):
    timestamp = time.strftime("%H:%M:%S")
    print(f"{COLORS['gray']}[{timestamp}] {level:5}{COLORS['reset']} {msg}", file=sys.stderr)


@dataclass
class Dashboard:
    """
    Real-time CLI dashboard for SKVA progress visualization.
    Uses ANSI colors and aligned text formatting without external dependencies.
    Renders phase, agent, file, error, and summary lines with consistent styling.
    """

    project_dir: Path
    width: int = 80
    enabled: bool = True
    start_time: float = 0.0
    stats: Dict[str, Any] = None

    def __post_init__(self):
        self.start_time = time.time()
        self.stats = {
            "phases": 0,
            "agents": 0,
            "files": 0,
            "errors": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
            "successful_agents": 0,
            "failed_agents": 0,
        }
        self._ensure_skva_dir()

    def _ensure_skva_dir(self):
        """Ensure .skva directory exists for logs or state (future use)."""
        skva_dir = self.project_dir / ".skva"
        try:
            skva_dir.mkdir(exist_ok=True)
        except Exception as e:
            log(f"Failed to create .skva dir: {e}", "WARNING")

    def _truncate(self, text: str, max_len: int) -> str:
        """Truncate text with ellipsis if needed."""
        if len(text) <= max_len:
            return text
        return text[:max_len - 1] + "…"

    def _color(self, text: str, color_key: str) -> str:
        """Apply ANSI color if stdout is a TTY."""
        if not self.enabled or not sys.stdout.isatty():
            return text
        return f"{COLORS[color_key]}{text}{COLORS['reset']}"

    def _clear_line(self):
        """Clear current line in terminal."""
        if sys.stdout.isatty():
            print("\r\033[K", end="")

    def _clear_screen(self):
        """Clear full screen and move cursor to top."""
        if not sys.stdout.isatty():
            return
        print("\033[2J\033[H", end="")

    def clear(self):
        """Clear screen for refresh."""
        self._clear_screen()

    def show_phase(self, name: str, status: str):
        """
        Print phase line with icon, name, and status.
        Example: 🔍 analyze — running
        """
        icon = ICONS.get(name, "🏗")
        status_colored = (
            self._color(status, "green") if status == "success"
            else self._color(status, "red") if status == "failed"
            else self._color(status, "yellow")
        )
        line = f"{icon} {name:<12} — {status_colored}"
        print(line)
        if status == "success":
            self.stats["phases"] += 1

    def show_agent(self, role: str, status: str, tokens: int = 0, files: int = 0, cost: float = 0.0):
        """
        Print agent line with role, status, token count, file count, and cost.
        Example: 🤖 reviewer — success (1.2k tokens, 2 files, ~$0.0024)
        """
        status_icon = (
            self._color("✅", "green") if status == "success"
            else self._color("❌", "red") if status == "failed"
            else self._color("⚠️", "yellow")
        )
        role_trunc = self._truncate(role, 18)
        tokens_str = f"{tokens / 1000:.1f}k" if tokens >= 1000 else str(tokens)
        cost_str = f"~${cost:.4f}" if cost > 0 else ""
        parts = [f"{tokens_str} токенів"] if tokens else []
        if files: parts.append(f"{files} файлів")
        if cost_str: parts.append(cost_str)
        details = ", ".join(parts) if parts else ""
        details_str = f" ({details})" if details else ""
        line = f"  {status_icon} {role_trunc:<20} — {details_str}"
        print(line.rstrip())
        self.stats["agents"] += 1
        self.stats["total_tokens"] += tokens
        self.stats["total_cost"] += cost
        if status == "success":
            self.stats["successful_agents"] += 1
        elif status == "failed":
            self.stats["failed_agents"] += 1

    def show_file(self, path: str, size: int):
        """
        Print file line with path and size.
        Example: 📄 src/main.py (482 bytes)
        """
        path_trunc = self._truncate(path, self.width - 20)
        size_unit = (
            f"{size / 1_000_000:.1f}M" if size >= 1_000_000
            else f"{size / 1000:.1f}k" if size >= 1000
            else str(size)
        )
        size_str = f"{size_unit} байт"
        line = f"  📄 {path_trunc} ({size_str})"
        print(line)
        self.stats["files"] += 1

    def show_error(self, code: str, msg: str):
        """
        Print error line with code and truncated message.
        Example: ⚠️ [PARSE_ERR] Invalid JSON in config (...)
        """
        code_colored = self._color(f"[{code}]", "red")
        msg_trunc = self._truncate(msg, self.width - 20)
        line = f"  ⚠️ {code_colored} {msg_trunc}"
        print(line, file=sys.stderr)
        self.stats["errors"] += 1

    def show_summary(self, stats: Dict[str, Any]):
        """
        Print final summary table with aligned columns and totals.
        Includes duration, phases, agents, files, tokens, cost.
        """
        self.clear()
        elapsed = time.time() - self.start_time
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        duration_str = f"{int(h):02}:{int(m):02}:{int(s):02}"

        # Combine provided stats with internal stats
        merged = {**self.stats, **stats}
        total_agents = merged.get("agents", 0)
        success_rate = (merged.get("successful_agents", 0) / total_agents * 100) if total_agents else 0

        print(self._color("🏁 ПІДСУМКИ ВИКОНАННЯ", "yellow"))
        print("=" * self.width)

        rows = [
            ("Тривалість", duration_str),
            ("Фази", str(merged.get("phases", 0))),
            ("Агенти", f"{total_agents} (успішно: {merged.get('successful_agents', 0)})"),
            ("Файли", str(merged.get("files", 0))),
            ("Токени", f"{merged.get('total_tokens', 0):,}"),
            ("Помилки", str(merged.get("errors", 0))),
            ("Оціночна вартість", f"${merged.get('total_cost', 0.0):.4f}"),
            ("Ефективність", f"{success_rate:.1f}%"),
        ]

        # Find max label width for alignment
        max_label = max(len(label) for label, _ in rows) + 2

        for label, value in rows:
            label_colored = self._color(f"{label}:", "cyan")
            print(f"  {label_colored:<{max_label}} {value}")

        print("=" * self.width)
        log("Dashboard summary displayed.", "INFO")


# Example usage (for testing only, not executed when imported)
if __name__ == "__main__":
    dash = Dashboard(project_dir=Path("."))
    dash.show_phase("analyze", "running")
    time.sleep(0.1)
    dash.show_agent("code_reviewer", "success", tokens=1250, files=2, cost=0.0024)
    dash.show_file("src/main.py", 482)
    dash.show_error("PARSE_ERR", "Failed to parse JSON configuration due to trailing comma.")
    dash.show_phase("analyze", "success")
    dash.show_summary({})
