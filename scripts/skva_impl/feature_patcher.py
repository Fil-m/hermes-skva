# SKVA FeaturePatcher
import re
from skva_core import multi_provider_call, log, parse_search_replace_blocks, apply_search_replace

# ═══════════════════════════════════════════════════
# FEATURE PATCHER — Generate & apply targeted code patches
# ═══════════════════════════════════════════════════

from typing import Dict, Any
import asyncio

# Assume these are available from core
from skva_core import (
    multi_provider_call,
    log,
    parse_search_replace_blocks,
    apply_search_replace
)


@dataclass
class FeaturePatcher:
    """
    FeaturePatcher generates precise code modifications to implement
    a single missing feature using LLM-guided SEARCH/REPLACE patches.
    Operates purely in memory, fully async, no direct file I/O.
    """

    model: str = "gpt-4o"
    provider: str = "openai"
    timeout: float = 30.0
    max_retries: int = 2

    async def patch(self, tz_section: str, code: str, feature: Dict[str, Any]) -> str:
        """
        Generate a SEARCH/REPLACE patch to implement the given feature.
        Uses the TZ (Task Zone) context to guide implementation.

        Args:
            tz_section: Contextual guidance from task planner
            code: Current version of the code (full string)
            feature: Dict describing the feature (name, description, params, etc.)

        Returns:
            Patched code string with the feature applied
        """
        prompt = (
            f"Add this feature: {json.dumps(feature, indent=2)}\n\n"
            f"Implementation guidance (TZ section):\n{tz_section}\n\n"
            f"Existing code (truncated if long):\n{code[:MAX_FILE_CHARS]}\n\n"
            f"Generate ONLY the minimal SEARCH/REPLACE block needed to implement this feature.\n"
            f"Do NOT include explanations, comments, or extra code.\n"
            f"Ensure imports, function definitions, and indentation are correct.\n"
            f"Return format:\n"
            f"