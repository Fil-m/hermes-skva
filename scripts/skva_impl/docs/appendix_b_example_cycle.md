```markdown
# Appendix B: Complete SKVA Example Cycle

This appendix provides a full end-to-end example of an SKVA (Systematic Knowledge Validation and Adjustment) cycle, illustrating how a user request is processed through method selection, phased execution, agent involvement, gate checks, checkpoints, retrospective analysis, and final result delivery.

---

## 1. User Request

A user submits a request to validate and improve the accuracy of a machine learning model documentation.

> **User Request**:  
> "Review the documentation for the `text-summarizer-v3` model, verify alignment with the latest training data and evaluation metrics, and update any outdated claims."

---

## 2. Method Selection

Based on the request type (documentation validation + factual alignment), the system selects the **SKVA-DOC-01** method, designed for technical documentation audits.

```bash
$ skva select-method --request="documentation audit" --domain="ML models" --output-format=json
{
  "selected_method": "SKVA-DOC-01",
  "description": "Structured validation of technical documentation against source artifacts",
  "phases": ["Planning", "Extraction", "Validation", "Adjustment", "Review"]
}
```

---

## 3. Phases

The SKVA-DOC-01 method executes through five sequential phases:

| Phase        | Purpose |
|--------------|--------|
| **Planning** | Define scope, sources, and success criteria |
| **Extraction** | Retrieve documentation and source data (code, metrics, logs) |
| **Validation** | Compare claims in docs against evidence |
| **Adjustment** | Propose and apply corrections |
| **Review** | Final verification and approval |

---

## 4. Agents

Each phase is managed by a specialized agent:

| Agent | Role | Tooling |
|-------|------|-------|
| `planner-agent` | Interprets request, sets scope | NLP parser, scope validator |
| `extractor-agent` | Pulls docs and artifacts | Git, MLflow, Data Lake API |
| `validator-agent` | Checks factual consistency | Diff engine, assertion checker |
| `editor-agent` | Edits documentation | Markdown editor, version control |
| `reviewer-agent` | Final approval | Compliance checker, SME interface |

```bash
$ skva list-agents --method=SKVA-DOC-01
planner-agent     [active]
extractor-agent   [active]
validator-agent   [active]
editor-agent      [active]
reviewer-agent    [active]
```

---

## 5. Gates

Each phase ends with a gate that must pass before proceeding.

| Gate | Condition | Outcome |
|------|---------|--------|
| G1: Scope Approval | 90%+ alignment between request and plan | ✅ Passed |
| G2: Artifact Completeness | All 5 source systems accessed successfully | ✅ Passed |
| G3: Discrepancy Threshold | <5 critical mismatches | ✅ Passed (3 found) |
| G4: Edit Sign-off | Changes reviewed by editor-agent | ✅ Passed |
| G5: Final Compliance | No open issues, version tagged | ✅ Passed |

```bash
$ skva check-gate --phase=Validation
{
  "gate": "G3",
  "status": "passed",
  "discrepancies": {
    "critical": 3,
    "warning": 7,
    "info": 12
  },
  "threshold": "critical < 5"
}
```

---

## 6. Checkpoints

Key checkpoints logged during execution:

| Phase | Checkpoint | Timestamp | Status |
|------|-----------|----------|--------|
| Planning | `CP-01: Scope finalized` | 2023-10-05T08:12:33Z | ✅ |
| Extraction | `CP-02: Metrics v2.4.1 retrieved` | 2023-10-05T08:25:11Z | ✅ |
| Validation | `CP-03: Claim mismatch in 'F1-score' detected` | 2023-10-05T08:41:02Z | ⚠️ |
| Adjustment | `CP-04: Docs updated in PR #284` | 2023-10-05T09:03:44Z | ✅ |
| Review | `CP-05: Approved by reviewer-agent` | 2023-10-05T09:15:20Z | ✅ |

```bash
$ skva log checkpoints --cycle-id=SKVA-2023-09876
CP-01: Scope finalized
CP-02: Metrics v2.4.1 retrieved
CP-03: Claim mismatch in 'F1-score' detected
CP-04: Docs updated in PR #284
CP-05: Approved by reviewer-agent
```

---

## 7. Retro

Post-execution retrospective analysis:

> **What went well**:  
> - Extractor-agent successfully integrated with MLflow and Git.  
> - Validator-agent caught 3 critical inaccuracies, including outdated latency claims.  
>
> **Improvements**:  
> - Reduce false positives in metric comparison logic.  
> - Add support for automatic citation linking in editor-agent.  
>
> **Cycle Metrics**:  
> - Duration: 63 minutes  
> - Agent handoffs: 5  
> - Edits applied: 7  
> - Human escalation: 0  

```bash
$ skva retro --cycle-id=SKVA-2023-09876 --format=summary
Retro completed. Recommendations logged to /retros/SKVA-2023-09876.md
```

---

## 8. Result

Final output delivered to user:

> ✅ **SKVA Cycle Complete**  
> - Method: SKVA-DOC-01  
> - Status: Success  
> - Updated Document: [`text-summarizer-v3.md`](/docs/ml/text-summarizer-v3.md)  
> - Changes:  
>   - Updated F1-score from 0.84 → 0.89 (v2.4.1)  
>   - Corrected training data size (2.1B → 2.3B tokens)  
>   - Added latency benchmarks for GPU T4  
> - PR: [#284](https://git.example.com/ml-docs/pull/284) (merged)  

```bash
$ skva result --cycle-id=SKVA-2023-09876
{
  "status": "success",
  "document": "text-summarizer-v3.md",
  "changes_applied": 7,
  "pr_url": "https://git.example.com/ml-docs/pull/284",
  "timestamp": "2023-10-05T09:16:01Z"
}
```

---
```