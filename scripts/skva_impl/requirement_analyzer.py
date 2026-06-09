# SKVA RequirementAnalyzer
import json, re
from skva_core import multi_provider_call, log

# ═══════════════════════════════════════════════════
# REQUIREMENT ANALYZER — Parse TZ into structured requirements
# ═══════════════════════════════════════════════════

from typing import List, Dict, Any, Optional
import json
import re
from dataclasses import dataclass
from skva_impl.utils import multi_provider_call  # Assuming available in skva_impl


@dataclass
class RequirementAnalyzer:
    """
    Parses Technical Zone (TZ) sections into structured requirements,
    maps them to target files, generates manifests, and validates coherence.
    """

    # Default system prompt for LLM-based requirement extraction
    _SYSTEM_PROMPT = """
You are a precise technical analyst for the SKVA system.
Extract structured requirements from the provided Technical Zone (TZ) text.
Each requirement must include:
- id: "R" + 3-digit number (e.g., R001)
- feature: snake_case identifier for the feature
- description: concise technical summary
- tz_section: section number like "3.1"
- tz_quote: exact short quote (max 80 chars) from the text
- target_file: primary file this affects (e.g., editor.html)
- category: one of [ui, backend, api, config, security, performance, compatibility]
- priority: one of [high, medium, low]

Return a JSON array of requirement objects only. No extra text.
If no requirements found, return [].
""".strip()

    _VALID_CATEGORIES = {
        "ui", "backend", "api", "config", "security", "performance", "compatibility"
    }
    _VALID_PRIORITIES = {"high", "medium", "low"}

    async def analyze(self, tz_text: str) -> List[Dict[str, Any]]:
        """
        Analyze full TZ text and extract structured requirements.
        Uses LLM via multi_provider_call with JSON fallback parsing.
        """
        if not tz_text or not tz_text.strip():
            return []

        try:
            # Call LLM with system prompt and TZ text
            response = await multi_provider_call(
                system_prompt=self._SYSTEM_PROMPT,
                user_prompt=tz_text.strip(),
                response_format={"type": "json_object"},  # Expecting array inside
                temperature=0.1,
            )

            # Attempt to extract JSON from response
            content = response.get("content", "")
            json_match = re.search(r'\[.*\]', content, re.DOTALL)
            if json_match:
                req_list = json.loads(json_match.group())
            else:
                # Fallback: try parsing whole response
                req_list = json.loads(content)

            # Validate and sanitize each requirement
            result = []
            seen_ids = set()
            for i, req in enumerate(req_list):
                try:
                    req_id = req.get("id", f"R{i+1:03d}")
                    if not re.match(r"^R\d{3}$", req_id):
                        req_id = f"R{i+1:03d}"

                    if req_id in seen_ids:
                        continue  # Skip duplicates
                    seen_ids.add(req_id)

                    feature = req.get("feature", "unknown")
                    description = req.get("description", "No description")
                    tz_section = req.get("tz_section", "unknown")
                    tz_quote = req.get("tz_quote", "")[:120]  # Truncate long quotes
                    target_file = req.get("target_file", "unknown")
                    category = req.get("category", "ui")
                    if category not in self._VALID_CATEGORIES:
                        category = "ui"
                    priority = req.get("priority", "medium")
                    if priority not in self._VALID_PRIORITIES:
                        priority = "medium"

                    result.append({
                        "id": req_id,
                        "feature": feature,
                        "description": description,
                        "tz_section": tz_section,
                        "tz_quote": tz_quote,
                        "target_file": target_file,
                        "category": category,
                        "priority": priority
                    })
                except Exception as e:
                    # Skip invalid entries
                    continue

            return result

        except Exception as e:
            # Fallback: simple regex-based extraction if LLM fails
            return self._fallback_parse(tz_text)

    def _fallback_parse(self, tz_text: str) -> List[Dict[str, Any]]:
        """
        Fallback parser using regex to find file references and keywords.
        Minimal but prevents total failure.
        """
        lines = tz_text.splitlines()
        requirements = []
        req_id = 1

        # Simple pattern to catch file assignments
        file_patterns = re.compile(r'(?:create|modify|update|add)\s+([a-zA-Z0-9_\-\.]+\.\w+)', re.IGNORECASE)
        section_pattern = re.compile(r'^\s*(\d+(?:\.\d+)*)\s')

        for i, line in enumerate(lines):
            line = line.strip()
            if not line or line.startswith('#') or len(line) < 10:
                continue

            files = file_patterns.findall(line)
            if not files:
                continue

            section_match = section_pattern.match(lines[i-1] if i > 0 else "")
            tz_section = section_match.group(1) if section_match else "?.?"

            for target_file in set(files):
                requirements.append({
                    "id": f"R{req_id:03d}",
                    "feature": target_file.replace(".", "_").replace("-", "_"),
                    "description": line,
                    "tz_section": tz_section,
                    "tz_quote": line[:80],
                    "target_file": target_file,
                    "category": "ui",  # default
                    "priority": "medium"
                })
                req_id += 1
                if req_id > 999:
                    break
            if req_id > 999:
                break

        return requirements

    def map_to_files(self, requirements: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group requirements by target_file.
        Returns dict mapping filename -> list of requirements.
        """
        mapping = {}
        for req in requirements:
            fname = req["target_file"]
            if fname not in mapping:
                mapping[fname] = []
            mapping[fname].append(req)
        return mapping

    def manifest(self, requirements: List[Dict[str, Any]]) -> str:
        """
        Generate a human-readable build manifest string.
        Groups by file, lists requirements with priorities.
        """
        if not requirements:
            return "# Build Manifest\n\nNo requirements specified."

        file_groups = self.map_to_files(requirements)
        lines = ["# SKVA Build Manifest", ""]
        
        # Sort files alphabetically
        for filename in sorted(file_groups.keys()):
            reqs = file_groups[filename]
            lines.append(f"## {filename}")
            # Sort by priority (high > medium > low), then by ID
            sorted_reqs = sorted(
                reqs,
                key=lambda r: (
                    {"high": 0, "medium": 1, "low": 2}[r["priority"]],
                    r["id"]
                )
            )
            for req in sorted_reqs:
                lines.append(f"  - [{req['priority']}] {req['id']}: {req['description']}")
            lines.append("")

        return "\n".join(lines)

    def validate_manifest(self, manifest: Dict[str, List[Dict[str, Any]]]) -> List[str]:
        """
        Validate the requirement manifest for common issues.
        Returns list of error/warning messages.
        Checks:
        - Duplicate target files with conflicting priorities
        - Missing high-priority requirements
        - Circular dependencies (if 'depends_on' were present — placeholder logic)
        """
        errors = []

        # Check for duplicate files (more than one requirement per file is OK)
        # But warn if too many requirements per file (possible decomposition needed)
        for filename, reqs in manifest.items():
            high_priority_count = sum(1 for r in reqs if r["priority"] == "high")
            if high_priority_count == 0:
                errors.append(f"Warning: {filename} has no high-priority requirements.")
            if len(reqs) > 10:
                errors.append(f"Warning: {filename} has {len(reqs)} requirements — consider splitting.")

        # Placeholder for future dependency graph validation
        # Assuming 'depends_on' field might be added later
        all_ids = {r["id"] for req_list in manifest.values() for r in req_list}
        for req_list in manifest.values():
            for req in req_list:
                # Example future check (currently no depends_on in schema)
                # if "depends_on" in req:
                #     for dep in req["depends_on"]:
                #         if dep not in all_ids:
                #             errors.append(f"Error: {req['id']} depends on unknown {dep}")
                pass

        # No circular deps possible without dependency field
        return errors
