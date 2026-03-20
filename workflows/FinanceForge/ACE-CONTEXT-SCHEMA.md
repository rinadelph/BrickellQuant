# ACE Context Schema
## Agentic Context Engineering — Living Context Document Specification
## FinanceForge Workflow

> **Core ACE Principle:** Context is a living, structured document that grows
> incrementally through the pipeline via delta bullets with metadata. It is NEVER
> rewritten monolithically. Monolithic rewriting caused context collapse in
> controlled research (18,282 tokens → 122 tokens, accuracy drop from 66.7% to
> 57.1%). Incremental delta updates achieved +10.6% on agent benchmarks.

---

## Document Structure

```
ACE_CONTEXT_{TICKER}_{DATE}.json
│
├── META                    ← Pipeline state, immutable after Phase 0
├── VERIFIED_DATA           ← All gatherer outputs (Phase 1 writes)
├── UNVERIFIED_FLAGS        ← Items requiring cross-reference
├── CONFLICT_LOG            ← Contradictions between gatherers (Phase 2 writes)
├── DISTRACTOR_LOG          ← Filtered distractors (Phase 2 writes, DO NOT READ)
├── VERIFICATION_GATE       ← Gate decision + rationale (Phase 2 writes)
├── EXPERT_POSITIONS        ← MoE council positions (Phase 3 writes)
├── SYNTHESIS_MEMO          ← Final weighted view (Macro Strategist writes)
├── SECTION_STATUS          ← Report section completion tracker (Phase 4 writes)
└── DELTA_LOG               ← All post-completion corrections (append only)
```

---

## Entry Format (Universal)

Every entry in every section uses this structure:

```json
{
  "entry_id": "UUID",
  "timestamp": "ISO-8601",
  "agent_id": "sec-edgar | financial-data | sentiment | macro | catalyst | source-verifier | bull | bear | quant | macro-strategist | report-orchestrator | latex | charting | diagram | viz | pdf-reviewer",
  "delta_type": "ADD | MODIFY | FLAG | REMOVE | REBUTTAL | SYNTHESIS",
  "confidence": "HIGH | MEDIUM | LOW | UNVERIFIED",
  "source_tier": "1 | 2 | 3 | NONE",
  "source_citation": {
    "source_name": "SEC EDGAR | Bloomberg | Reddit | etc.",
    "document_ref": "Accession number, URL, or filing identifier",
    "document_date": "ISO-8601",
    "section_ref": "Item 1A, Note 8, etc."
  },
  "data_labels": ["RPT | EST | STALE | SINGLE_SOURCE | HTML_PARSED | DISTRACTOR_RISK"],
  "payload": "The actual data, finding, position, or flag"
}
```

**Key rule:** The `payload` field is a structured string (not prose). Use the
financial bullet format:
`[METRIC]: [VALUE] ([LABEL]) — [CONTEXT]`

Examples:
```
"payload": "REVENUE_FY2024: $88.9B (RPT) — Source: 10-K FY2024, p.52, XBRL tag us-gaap:Revenues"
"payload": "SHARES_BASIC: 24.3M (RPT) — Source: 10-Q Q3 2024 cover page, EDGAR accession 0001234567-24-000789"
"payload": "EPS_FY2025E: $4.20 (EST) — Source: Bloomberg consensus, 12 analysts, data date 2024-03-15 [SINGLE_SOURCE]"
```

---

## Section Specifications

### META (Immutable after Phase 0)

```json
{
  "ticker": "string",
  "exchange": "string",
  "cik": "string (10-digit zero-padded)",
  "isin": "string | null",
  "company_name": "string",
  "analysis_date": "ISO-8601",
  "market_status": "OPEN | PRE_MARKET | AFTER_HOURS | CLOSED | WEEKEND",
  "fiscal_year_end": "MM-DD",
  "filing_date_map": {
    "latest_10K": {"date": "ISO-8601", "accession": "string"},
    "latest_10Q": {"date": "ISO-8601", "accession": "string"},
    "latest_8K":  {"date": "ISO-8601", "accession": "string"}
  },
  "pipeline_run_id": "UUID",
  "initialized_by": "phase-0-preflight"
}
```

**Write rule:** SET ONCE at Phase 0. No agent may modify META entries.
If a conflict with META is discovered (e.g., CIK mismatch), write to CONFLICT_LOG
— do NOT edit META.

---

### VERIFIED_DATA (Phase 1 writes — gatherers only)

This is the primary data store. All report content must trace back to an entry here.

**Sub-sections by domain:**

```
VERIFIED_DATA
├── FILINGS             ← sec-edgar-gatherer writes
│   ├── 10K_LATEST
│   ├── 10Q_LATEST
│   ├── 8K_RECENT       (last 6 months)
│   ├── FORM4_RECENT    (last 90 days)
│   └── DEF14A_LATEST
│
├── FINANCIALS          ← financial-data-gatherer writes
│   ├── INCOME_STATEMENT
│   ├── BALANCE_SHEET
│   ├── CASH_FLOW
│   ├── RATIOS
│   ├── CONSENSUS_ESTIMATES
│   └── PEER_COMPS
│
├── SENTIMENT           ← sentiment-gatherer writes
│   ├── REDDIT_SCORE
│   ├── STOCKTWITS_SCORE
│   ├── GOOGLE_TRENDS
│   ├── ANALYST_COVERAGE
│   └── DISCOVERY_LEVEL
│
├── MACRO               ← macro-gatherer writes
│   ├── SECTOR_TAILWINDS
│   ├── GEOPOLITICAL_EXPOSURE
│   └── THEME_ALIGNMENT
│
└── CATALYSTS           ← catalyst-tracker writes
    ├── EARNINGS_CALENDAR
    ├── REGULATORY_MILESTONES
    └── CONTRACT_PIPELINE
```

**Write rules for gatherers:**
1. Only write to your designated sub-section
2. One entry per distinct data point — do not bundle multiple metrics in one entry
3. If a data point is uncertain: set `confidence: UNVERIFIED` and write to
   UNVERIFIED_FLAGS as well
4. If a data point contradicts META: write to CONFLICT_LOG, do not modify VERIFIED_DATA
5. NEVER delete or overwrite an existing entry — use `delta_type: MODIFY` with
   rationale, or `delta_type: REMOVE` with reason

**Read rules:**
- Phase 2 (verifier): reads ALL sub-sections
- Phase 3 (experts): reads ALL sub-sections EXCEPT entries in DISTRACTOR_LOG
- Phase 4 (orchestrator): reads FILTERED sub-sections per section being written
- Phase 5 (presentation): reads FINANCIALS + FILINGS for chart data
- Phase 6 (reviewer): reads ALL for cross-verification

---

### UNVERIFIED_FLAGS (Phase 1 writes, Phase 2 resolves)

Entries that a gatherer could not cross-reference.

```json
{
  "flag_id": "UUID",
  "agent_id": "string",
  "timestamp": "ISO-8601",
  "data_point": "The specific figure or fact in question",
  "reason": "SINGLE_SOURCE | HTML_PARSED | STALE | CONTRADICTS_META | AMBIGUOUS",
  "resolution": "UNRESOLVED | CONFIRMED | REJECTED | REPLACED",
  "resolved_by": "source-verifier | null",
  "resolved_at": "ISO-8601 | null"
}
```

**Resolution logic (source-verifier):**
- `CONFIRMED`: Second source found, flag cleared, entry remains in VERIFIED_DATA
- `REJECTED`: Data point is wrong/irrelevant — add `delta_type: REMOVE` to
  VERIFIED_DATA entry
- `REPLACED`: Better source found — add `delta_type: MODIFY` to VERIFIED_DATA entry
- `UNRESOLVED`: Cannot verify — entry stays in VERIFIED_DATA with `[SINGLE_SOURCE]`
  label visible to expert agents

---

### CONFLICT_LOG (Phase 2 writes)

Contradictions between two or more gatherer outputs on the same metric.

```json
{
  "conflict_id": "UUID",
  "timestamp": "ISO-8601",
  "metric": "The financial metric or data point in conflict",
  "position_a": {
    "agent_id": "string",
    "value": "string",
    "source": "string",
    "confidence": "string"
  },
  "position_b": {
    "agent_id": "string",
    "value": "string",
    "source": "string",
    "confidence": "string"
  },
  "resolution": "USE_A | USE_B | USE_CONSERVATIVE | UNRESOLVED",
  "resolution_rationale": "string",
  "resolved_value": "string",
  "visible_to_experts": true
}
```

**Conflict resolution principle:**
When two sources disagree on a financial figure, the source-verifier:
1. Identifies which source is closer to Tier 1 (EDGAR)
2. Uses the more conservative figure
3. Sets `visible_to_experts: true` — experts MUST see conflicts
4. Expert agents acknowledge conflicts in their positions with:
   `[DATA CONFLICT: see CONFLICT_LOG {conflict_id}]`

---

### DISTRACTOR_LOG (Phase 2 writes — DO NOT READ after Phase 2)

Data identified as related-but-not-relevant (per The Distracting Effect research).
This data is quarantined from Phase 3 onward to prevent accuracy degradation.

```json
{
  "distractor_id": "UUID",
  "original_entry_id": "UUID",
  "distractor_type": "RELATED_TOPIC | HYPOTHETICAL | NEGATION | MODAL_STATEMENT",
  "reason": "string — why this is a distractor not signal",
  "quarantine_date": "ISO-8601",
  "quarantined_by": "source-verifier"
}
```

**Critical rule:** Expert agents (Phase 3) MUST filter DISTRACTOR_LOG IDs from
their context reads. A modal statement distractor ("The company may have exposure
to X...") is the most dangerous type — mimics authoritative text, reduces accuracy
by up to 11 points per research.

---

### VERIFICATION_GATE (Phase 2 writes — one entry only)

```json
{
  "timestamp": "ISO-8601",
  "agent_id": "source-verifier",
  "decision": "PASS | CONDITIONAL_PASS | BLOCK",
  "data_coverage_pct": "number (0-100)",
  "unverified_flag_count": "number",
  "conflict_count": "number",
  "critical_gaps": ["list of missing critical data fields"],
  "conditional_notes": "string — what experts should be aware of",
  "block_reason": "string | null"
}
```

---

### EXPERT_POSITIONS (Phase 3 writes — experts only)

One sub-section per expert. Graph topology: each expert can read all others.

```
EXPERT_POSITIONS
├── BULL        ← bull-analyst writes
├── BEAR        ← bear-analyst writes
├── QUANT       ← quant-analyst writes
└── MACRO       ← macro-strategist writes (also writes SYNTHESIS_MEMO)
```

**Round structure enforcement:**

```
Round 1 entries:  delta_type = "ADD", round = 1
Round 2 entries:  delta_type = "ADD" or "REBUTTAL", round = 2
                  REBUTTAL entries MUST reference the entry_id they rebut
```

**Entry format for expert positions:**

```json
{
  "entry_id": "UUID",
  "agent_id": "bull | bear | quant | macro",
  "round": 1 | 2,
  "delta_type": "ADD | REBUTTAL",
  "rebutting": "entry_id | null",
  "confidence": "HIGH | MEDIUM | LOW",
  "position_type": "THESIS | EVIDENCE | CONCERN | AGREEMENT | ARITHMETIC",
  "payload": "Position statement with specific data citation",
  "data_citations": ["entry_id from VERIFIED_DATA that supports this position"],
  "speculative_flag": "boolean — true if position requires assumptions beyond verified data"
}
```

---

### SYNTHESIS_MEMO (Macro Strategist writes — Phase 3, Round 3 only)

The definitive output of the MoE council. Report-orchestrator treats this as
the primary analytical input — more authoritative than individual EXPERT_POSITIONS.

```json
{
  "timestamp": "ISO-8601",
  "author": "macro-strategist",
  "base_case": {
    "description": "string",
    "probability_pct": "number",
    "price_target": "number",
    "key_assumptions": ["list"],
    "key_risks": ["list"]
  },
  "bull_case": {
    "description": "string",
    "probability_pct": "number",
    "price_target": "number",
    "required_catalyst": "string",
    "speculative_assumptions": ["list — items beyond verified data"]
  },
  "bear_case": {
    "description": "string",
    "probability_pct": "number",
    "price_target": "number",
    "trigger_scenario": "string",
    "speculative_assumptions": ["list"]
  },
  "unresolved_disagreements": [
    {
      "topic": "string",
      "bull_position": "entry_id",
      "bear_position": "entry_id",
      "quant_verdict": "entry_id | null",
      "resolution": "UNRESOLVED — FLAGGED FOR READER"
    }
  ],
  "probability_sum_check": "number — must equal 100"
}
```

**Validation rule:** `base_case.probability_pct + bull_case.probability_pct +
bear_case.probability_pct` MUST equal 100. If not, the synthesis is invalid and
the report-orchestrator must flag it.

---

### SECTION_STATUS (Phase 4 writes — report-orchestrator only)

Tracks 15-section report completion. Prevents context collapse by enabling
section-level context filtering.

```json
{
  "section_id": "I | II | III | IV | V | VI | VII | VIII | IX | X | XI | XII | XIII | XIV | XV",
  "title": "string",
  "status": "PENDING | IN_PROGRESS | COMPLETE | FAILED | SKIPPED",
  "started_at": "ISO-8601 | null",
  "completed_at": "ISO-8601 | null",
  "data_sources_used": ["list of VERIFIED_DATA entry_ids"],
  "synthesis_sections_used": ["bull_case | bear_case | base_case | etc."],
  "internal_consistency_flags": ["list of cross-section dependencies"],
  "word_count": "number",
  "figures_referenced": ["list of chart/diagram IDs"]
}
```

**Incremental write rule:** Section status is NEVER overwritten after `COMPLETE`.
Post-completion corrections go to DELTA_LOG only.

---

### DELTA_LOG (Append-only — any agent may write)

All corrections, updates, and revisions after a section or data point is marked
COMPLETE. This is the audit trail for the entire pipeline run.

```json
{
  "delta_id": "UUID",
  "timestamp": "ISO-8601",
  "agent_id": "string",
  "target": "section_id | entry_id",
  "delta_type": "CORRECTION | ADDITION | REMOVAL | FORMAT_FIX | DATA_UPDATE",
  "original_value": "string",
  "new_value": "string",
  "reason": "string",
  "triggered_by": "pdf-reviewer issue_id | source-verifier flag_id | manual"
}
```

---

## Collapse Prevention Rules

These rules prevent the context window collapse phenomenon observed in monolithic
rewriting approaches. EVERY agent must follow them.

```
RULE 1: Never rewrite a section — only append delta entries.
        If you need to change a VERIFIED_DATA entry, use delta_type: MODIFY
        and keep the original entry with its original timestamp.

RULE 2: Never load the full context window when writing a section.
        Request only the entries relevant to your current task via section tags.
        The report-orchestrator requests ONLY the data tagged for the current
        section being written (e.g., "pull all entries tagged for Section VIII").

RULE 3: Summarize stale intermediate context.
        After Phase 3 is complete, the EXPERT_POSITIONS (Round 1 + Round 2 raw
        entries) may be summarized to the SYNTHESIS_MEMO key points only.
        The full Round 1/2 entries are archived but not included in Phase 4
        context windows.

RULE 4: Prioritize recency within a section.
        When multiple entries exist for the same data point (e.g., multiple
        modifications), only the most recent MODIFY entry is loaded.
        Prior versions remain in the log but are tagged [SUPERSEDED].

RULE 5: Expert agents read FILTERED context.
        Experts do NOT receive the full VERIFIED_DATA dump.
        They receive a pre-filtered view with distractors removed and
        per-domain relevance applied (e.g., Bull analyst gets full FINANCIALS
        + CATALYSTS, but only summary SENTIMENT).
```

---

## Context Budget Guidelines (per ACE research)

> "Context packing will end in situations where you forget. LLM performance degrades
> as context size increases." — Loker, CodeRabbit

| Agent | Max Context Budget | What to Include |
|---|---|---|
| Gatherers (Phase 1) | Small — META + filing dates only | Just enough to know what to fetch |
| Verifier (Phase 2) | Full VERIFIED_DATA | Needs everything to detect conflicts |
| Expert agents (Phase 3) | Filtered VERIFIED_DATA + CONFLICT_LOG | No full prose, structured bullets only |
| Report Orchestrator (Phase 4) | Section-relevant slice + SYNTHESIS_MEMO | One section's data at a time |
| Presentation agents (Phase 5) | Specific data entries + report section | Only what is needed for current artifact |
| PDF Reviewer (Phase 6) | Full report + SECTION_STATUS + VERIFIED_DATA | Needs to cross-verify everything |

**Skill budget (per ACE research):** 2-3 focused skills per agent is optimal.
4+ skills collapse effectiveness. Comprehensive documentation hurts (-2.9pp).
Each agent file in this workflow is intentionally limited to 2-3 focused skills.

---

## Context Initialization Template

This is the blank ACE context document created at Phase 0.
Copy this template for each new research run.

```json
{
  "META": {},
  "VERIFIED_DATA": {
    "FILINGS": {},
    "FINANCIALS": {},
    "SENTIMENT": {},
    "MACRO": {},
    "CATALYSTS": {}
  },
  "UNVERIFIED_FLAGS": [],
  "CONFLICT_LOG": [],
  "DISTRACTOR_LOG": [],
  "VERIFICATION_GATE": null,
  "EXPERT_POSITIONS": {
    "BULL": [],
    "BEAR": [],
    "QUANT": [],
    "MACRO": []
  },
  "SYNTHESIS_MEMO": null,
  "SECTION_STATUS": {
    "I":   {"status": "PENDING"},
    "II":  {"status": "PENDING"},
    "III": {"status": "PENDING"},
    "IV":  {"status": "PENDING"},
    "V":   {"status": "PENDING"},
    "VI":  {"status": "PENDING"},
    "VII": {"status": "PENDING"},
    "VIII":{"status": "PENDING"},
    "IX":  {"status": "PENDING"},
    "X":   {"status": "PENDING"},
    "XI":  {"status": "PENDING"},
    "XII": {"status": "PENDING"},
    "XIII":{"status": "PENDING"},
    "XIV": {"status": "PENDING"},
    "XV":  {"status": "PENDING"}
  },
  "DELTA_LOG": []
}
```

---

*ACE Context Schema v2.0*
*Agentic Context Engineering for FinanceForge*
*Based on: ACE (Agentic Context Engineering) research — +10.6% benchmark improvement*
*Distractor filtering: The Distracting Effect — up to 11pp accuracy preservation*
