# SKVA SpecAuditor
import json
from skva_core import multi_provider_call, log

# ═══════════════════════════════════════════════════
# SPEC AUDITOR — Validate generated code against TZ spec
# ═══════════════════════════════════════════════════

from typing import List, Dict, Any
from skva_core import multi_provider_call, log


@dataclass
class SpecAuditor:
    """
    Compares generated code against the TZ (Technical Zone) specification section
    to identify missing or incomplete features using LLM-based semantic analysis.
    
    Pure async — no file I/O. Operates solely on string inputs and returns structured results.
    """

    async def audit(self, tz_section: str, code: str) -> List[Dict[str, Any]]:
        """
        Analyze whether the provided code implements all features described in the TZ section.
        
        Args:
            tz_section: The technical specification text (TZ section)
            code: The generated implementation code to validate
            
        Returns:
            List of missing features with details:
            [
                {
                    "feature": "pixel_lifetime",
                    "severity": "high",  # high | medium | low
                    "tz_quote": "Each pixel must carry a timestamp...",
                    "fix": "Add timestamp field and update lifecycle handler..."
                },
                ...
            ]
        """
        if not tz_section.strip():
            log("SpecAuditor.audit: tz_section is empty", level="warning")
            return []

        if not code.strip():
            log("SpecAuditor.audit: code is empty", level="warning")
            return []

        prompt = f'''
You are a senior software auditor. Your task is to compare the following technical specification (TZ section)
with the provided implementation code and identify any missing or incomplete features.

Only report features that are clearly described in the TZ but not implemented in the code.
Do not report stylistic or performance issues unless explicitly required by the spec.

For each missing feature, return:
- feature: short identifier (snake_case)
- severity: high (core functionality), medium (important), low (optional/nice-to-have)
- tz_quote: verbatim short excerpt from TZ justifying the feature
- fix: concise implementation suggestion

TZ SPECIFICATION:
