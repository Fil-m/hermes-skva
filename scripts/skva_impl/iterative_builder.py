# SKVA IterativeBuilder
import sys, os, json, time, asyncio
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log, multi_provider_call

# ═══════════════════════════════════════════════════
# ITERATIVE BUILDER — Full module orchestration via spec-driven iteration
# ═══════════════════════════════════════════════════

from skva_impl.spec_auditor import SpecAuditor
from skva_impl.feature_patcher import FeaturePatcher
from typing import Dict, List, Any, Tuple
from pathlib import Path
import asyncio
import json
import logging

# Configure logger
logger = logging.getLogger(__name__)


class IterativeBuilder:
    """
    Orchestrate the full iterative pipeline for building a single module
    based on a spec (TZ section), using audit-and-patch cycles until completeness.
    """

    def __init__(self, provider: str = "auto", model: str = "smart"):
        self.provider = provider
        self.model = model
        self.spec_auditor = SpecAuditor()
        self.feature_patcher = FeaturePatcher(provider=provider, model=model)

    async def build_module(
        self,
        tz_section: Dict[str, Any],
        module_name: str,
        output_file: Path,
        max_iterations: int = 5,
    ) -> bool:
        """
        Iteratively build a module by:
        1. Generating base code from spec
        2. Auditing for missing features
        3. Patching missing features until complete or max iterations reached
        4. Writing final code to file

        Returns True if any code was generated (even if incomplete).
        """
        report = get_report()
        node_id = f"build.{module_name}"
        attempt = 1
        max_retries = 1  # No retries per se, but fits RunRecord schema
        start_time = time.time()

        if report:
            run_rec = report.start_agent(node_id, "IterativeBuilder", self.model, attempt, max_retries)
            run_rec.provider = self.provider
            run_rec.model_name = self.model

        logger.info(f"Starting iterative build for module: {module_name}")

        # Step 1: Generate base code from spec
        base_prompt = self._construct_base_prompt(tz_section)
        try:
            response = await self._multi_provider_call(base_prompt)
            current_code = response.get("content", "").strip()
            if report:
                run_rec.input_tokens += response.get("input_tokens", 0)
                run_rec.output_tokens += response.get("output_tokens", 0)
        except Exception as e:
            if report:
                run_rec.status = "failed"
                run_rec.error_code = "CODEGEN_FAILED"
                run_rec.error_message = str(e)
            logger.error(f"Base code generation failed for {module_name}: {e}")
            return False

        if not current_code:
            if report:
                run_rec.status = "failed"
                run_rec.error_code = "EMPTY_RESPONSE"
                run_rec.error_message = "No code generated in initial step"
            return False

        logger.debug(f"Generated base code for {module_name} ({len(current_code)} chars)")

        # Step 2: Iterative audit-and-patch loop
        iteration = 0
        completed = False
        patches_applied = 0

        while iteration < max_iterations and not completed:
            iteration += 1
            logger.info(f"Iteration {iteration}/{max_iterations} for {module_name}")

            # a. Audit current code against spec
            try:
                audit_result = await self.spec_auditor.audit(tz_section, current_code)
                missing_features = audit_result.get("missing", [])
                if not missing_features:
                    completed = True
                    logger.info(f"Module {module_name} complete after {iteration} iterations.")
                    break
                logger.info(f"Found {len(missing_features)} missing features in iteration {iteration}")
            except Exception as e:
                logger.warning(f"Audit failed in iteration {iteration}, continuing: {e}")
                continue

            # b. Patch each missing feature
            for feature in missing_features:
                try:
                    patch_result = await self.feature_patcher.patch(
                        tz_section, current_code, feature
                    )
                    patch_code = patch_result.get("patch", "").strip()
                    if not patch_code:
                        logger.debug(f"No patch generated for feature: {feature.get('title', 'unknown')}")
                        continue

                    # Apply patch (simple concatenation or smarter merge can be added)
                    if "def " in patch_code or "class " in patch_code:
                        current_code += "\n\n" + patch_code
                    else:
                        current_code += "\n" + patch_code

                    patches_applied += 1
                    if report:
                        run_rec.patches_applied += 1

                    logger.debug(f"Applied patch for feature: {feature.get('title', 'unknown')}")

                except Exception as e:
                    logger.warning(f"Failed to patch feature: {e}")
                    continue

            # Log progress
            logger.info(
                f"Iteration {iteration} complete. Patches applied: {patches_applied}, "
                f"Code size: {len(current_code)} chars"
            )

        # Step 3: Write final code to output file
        try:
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(current_code, encoding="utf-8")
            if report:
                run_rec.files_written += 1
            logger.info(f"Final code written to {output_file}")
        except Exception as e:
            if report:
                run_rec.status = "failed"
                run_rec.error_code = "WRITE_FAILED"
                run_rec.error_message = str(e)
            logger.error(f"Failed to write output file {output_file}: {e}")
            return False

        # Finalize report
        if report:
            run_rec.status = "success" if completed else "partial"
            run_rec.duration = time.time() - start_time
            run_rec.total_tokens = run_rec.input_tokens + run_rec.output_tokens

        return True

    async def build_project(
        self,
        tz_chunks: List[Dict[str, Any]],
        module_configs: Dict[str, Dict[str, Any]],
        output_dir: Path,
    ) -> Dict[str, Any]:
        """
        Build multiple modules in parallel based on TZ chunks and module configs.

        tz_chunks: List of spec sections (each corresponding to a module)
        module_configs: {module_name: {output_file, ...}}
        output_dir: Base directory for outputs

        Returns summary stats.
        """
        start_time = time.time()
        results = {}
        tasks = []

        for tz_section in tz_chunks:
            module_name = tz_section.get("module", tz_section.get("name", "unknown"))
            config = module_configs.get(module_name)
            if not config:
                logger.warning(f"No config found for module: {module_name}")
                continue

            output_file = output_dir / config["output_file"]
            task = asyncio.create_task(
                self.build_module(tz_section, module_name, output_file)
            )
            tasks.append((module_name, task))

        # Run all module builds concurrently
        for module_name, task in tasks:
            try:
                success = await task
                results[module_name] = {"success": success, "error": None}
            except Exception as e:
                logger.error(f"Build failed for module {module_name}: {e}")
                results[module_name] = {"success": False, "error": str(e)}

        total_success = sum(1 for r in results.values() if r["success"])
        total_modules = len(results)

        return {
            "total_modules": total_modules,
            "completed": total_success,
            "failed": total_modules - total_success,
            "success_rate": total_success / total_modules if total_modules else 0,
            "duration": time.time() - start_time,
            "results": results,
            "output_dir": str(output_dir),
        }

    def _construct_base_prompt(self, tz_section: Dict[str, Any]) -> str:
        """Construct prompt for base code generation from spec."""
        title = tz_section.get("title", "Module")
        description = tz_section.get("description", "")
        requirements = tz_section.get("requirements", [])
        req_text = "\n".join(f"- {req}" for req in requirements)

        return f"""
Write Python code for a module: {title}

Description:
{description}

Requirements:
{req_text}

Provide only the implementation code. No explanations.
Ensure all required functionality is included.
Use clear, maintainable code with type hints where appropriate.
        """.strip()

    async def _multi_provider_call(self, prompt: str) -> Dict[str, Any]:
        """
        Placeholder for actual multi-provider LLM call.
        In real implementation, this would route to smart_model or fallbacks.
        """
        # Simulate async LLM call
        await asyncio.sleep(0.1)

        # This should be replaced with actual provider logic (e.g., from skva_impl.providers)
        # For now, return mock response
        return {
            "content": f'# Generated code for "{prompt.split()[0]}"\n\ndef placeholder():\n    """Auto-generated module."""\n    pass\n',
            "input_tokens": 150,
            "output_tokens": 75,
            "model": self.model,
            "provider": self.provider,
        }
