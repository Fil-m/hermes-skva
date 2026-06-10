"""SKVA Entity Schema — читає YAML схему сутностей, генерує код."""
import json, yaml, re
from pathlib import Path
from skva_core import log, multi_provider_call

class EntitySchema:
    def __init__(self, path_or_dict):
        if isinstance(path_or_dict, (str, Path)):
            with open(path_or_dict) as f:
                self.data = yaml.safe_load(f)
        else:
            self.data = path_or_dict
        self.entities = self.data.get('entities', {})
    
    def describe(self) -> str:
        """Generate text description of all entities for LLM prompts."""
        lines = ["Entity Schema:", ""]
        for name, info in self.entities.items():
            lines.append(f"## {name}")
            lines.append("Properties:")
            for prop, typ in info.get('props', {}).items():
                if isinstance(typ, dict):
                    t = typ.get('type', 'string')
                    if 'values' in typ:
                        t = f"enum({','.join(typ['values'])})"
                    lines.append(f"  - {prop}: {t}")
                else:
                    lines.append(f"  - {prop}: {typ}")
            for rel in info.get('relations', []):
                lines.append(f"  - {rel.get('type','ref')} -> {rel.get('entity','?')}")
            lines.append("")
        return '\n'.join(lines)
    
    def generate_prompt(self, target_entity: str) -> str:
        """Generate a focused code prompt for one entity."""
        info = self.entities.get(target_entity)
        if not info: return ""
        prompt = f"Implement the {target_entity} class/component.\n\n"
        prompt += f"Properties:\n"
        for prop, typ in info.get('props', {}).items():
            if isinstance(typ, dict):
                t = typ.get('type', 'string')
                if 'values' in typ:
                    t = f"enum({','.join(typ['values'])})"
                if 'default' in typ:
                    t += f" (default: {typ['default']})"
                prompt += f"- {prop}: {t}\n"
            else:
                prompt += f"- {prop}: {typ}\n"
        prompt += f"\nRelations:\n"
        for rel in info.get('relations', []):
            prompt += f"- {rel.get('type')} {rel.get('entity')}\n"
        return prompt
    
    async def audit_code(self, code: str) -> list:
        """Check if code implements all entities from schema."""
        desc = self.describe()
        prompt = f"""Check if this code implements ALL entities from the schema.

SCHEMA:
{desc[:3000]}

CODE:
{code[:3000]}

List ALL entities or properties that are MISSING or INCORRECT.
JSON: [{{"entity":"...","missing":["prop1","prop2"],"issues":["..."], "severity":"high|med"}}]
JSON ONLY."""
        text, it, ot = await multi_provider_call(prompt, timeout=120)
        m = re.search(r'\[.*\]', text or '', re.DOTALL)
        if m:
            try: return json.loads(m.group(0))
            except: pass
        return []
    
    def to_yaml(self) -> str:
        return yaml.dump(self.data, default_flow_style=False, allow_unicode=True)

    def to_files(self) -> dict:
        """Map entities to output files based on type."""
        files = {}
        for name in self.entities:
            # Heuristic: entity → file mapping
            name_lower = name.lower()
            if name_lower in ('user', 'player'):
                files[f'{name_lower}.js'] = [name]
            elif name_lower in ('canvas', 'pixel'):
                files['pixel-editor.js'] = files.get('pixel-editor.js', []) + [name]
            elif name_lower == 'engine':
                files['engines.js'] = [name]
            elif name_lower == 'skin':
                files['shop.js'] = [name]
            else:
                files[f'{name_lower}.js'] = [name]
        return files
