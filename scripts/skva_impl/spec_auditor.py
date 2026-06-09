"""SKVA SpecAuditor — compare code against TZ section."""
import json, re
from skva_core import multi_provider_call, log

class SpecAuditor:
    """Compare generated code against TZ section, return list of missing features."""

    async def audit(self, tz_section: str, code: str) -> list:
        prompt = f"""Compare this TZ section with the code below. List ALL features from TZ that are NOT implemented in code.

TZ:
{tz_section[:3000]}

CODE:
{code[:3000]}

Return JSON list: [{{"feature":"...","severity":"high|med|low","tz_quote":"...","fix":"..."}}]
JSON ONLY."""
        text, it, ot = await multi_provider_call(prompt, timeout=120)
        if not text:
            return []
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except:
                pass
        return []

    def format_report(self, missing: list) -> str:
        if not missing:
            return "✅ All requirements implemented"
        lines = [f"⚠️ {len(missing)} missing features:"]
        for m in missing:
            lines.append(f"  [{m.get('severity','?')}] {m.get('feature','?')}: {m.get('fix','')[:80]}")
        return "\n".join(lines)

    def severity(self, missing_count: int) -> str:
        if missing_count == 0: return "done"
        if missing_count < 3: return "improving"
        return "many"
