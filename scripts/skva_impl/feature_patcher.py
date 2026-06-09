"""SKVA FeaturePatcher — generate focused code patches for missing features."""
import re
from skva_core import multi_provider_call, log

class FeaturePatcher:
    """Generate a focused code patch for ONE missing feature."""

    async def patch(self, tz_section: str, code: str, feature: dict) -> str:
        prompt = f"""Add this missing feature to the code.

FEATURE: {feature.get('feature', 'unknown')}
SEVERITY: {feature.get('severity', 'medium')}
TZ SAYS: {feature.get('tz_quote', '')}
FIX SUGGESTION: {feature.get('fix', '')}

EXISTING CODE:
{code[:3000]}

Generate ONLY the code changes. Use SEARCH/REPLACE format:
<<<<<<< SEARCH
[exact existing code]
=======
[new code with feature added]
>>>>>>> REPLACE"""
        text, it, ot = await multi_provider_call(prompt, timeout=120)
        return text or ""

    def apply_patch(self, code: str, patch_text: str) -> str:
        """Apply SEARCH/REPLACE patch to code."""
        blocks = re.findall(
            r'<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE',
            patch_text, re.DOTALL
        )
        result = code
        for old, new in blocks:
            if old.strip() in result:
                result = result.replace(old.strip(), new.strip())
            else:
                log(f"  Patch target not found, appending", "WARN")
                result += f"\n\n# ADDED: {new[:100]}...\n{new}"
        return result

    def estimate_complexity(self, feature: dict) -> int:
        sev = feature.get('severity', 'medium')
        return {"high": 5, "medium": 3, "low": 1}.get(sev, 2)
