# FinanceForge Workflow
## Institutional Equity Research Pipeline — ACE Architecture

> **Design Principle (from ACE Research):** This is a workflow with intelligence
> inserted at specific nodes — not an autonomous agent roaming free. Deterministic
> steps handle what we know. Agentic loops handle judgment. Context is a living,
> structured document that grows incrementally through the pipeline.

---

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FINANCEFORGE PIPELINE                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  PHASE 0: DETERMINISTIC PRE-FLIGHT                                  │
│  ──────────────────────────────────────────────────────────────     │
│  Validate ticker → Resolve CIK → Check market status →             │
│  Initialize ACE context → Map data requirements                     │
│                           │                                         │
│                           ▼                                         │
│  PHASE 1: PARALLEL DATA GATHERING (Independent streams)             │
│  ──────────────────────────────────────────────────────────────     │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐               │
│  │  SEC-EDGAR   │ │  FINANCIAL   │ │  SENTIMENT   │               │
│  │  GATHERER    │ │  DATA        │ │  GATHERER    │               │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘               │
│         │          ┌──────┴───────┐        │                        │
│         │          │    MACRO     │        │                        │
│         │          │  GATHERER   │        │                        │
│         │          └──────┬───────┘        │                        │
│         │         ┌───────┴──────┐         │                        │
│         │         │  CATALYST    │         │                        │
│         │         │  TRACKER     │         │                        │
│         │         └──────┬───────┘         │                        │
│         └────────────────┴─────────────────┘                        │
│                           │                                         │
│                     [All write to ACE context: VERIFIED_DATA]       │
│                           │                                         │
│                           ▼                                         │
│  PHASE 2: VERIFICATION GATE ◄── BLOCK if critical data missing      │
│  ──────────────────────────────────────────────────────────────     │
│  SOURCE-VERIFIER: conflict detection, freshness audit,              │
│  distractor filtering, completeness check                           │
│  Gate decision: PASS / CONDITIONAL_PASS / BLOCK                     │
│                           │                                         │
│                     [Writes: CONFLICT_LOG, UNVERIFIED_FLAGS]        │
│                           │                                         │
│                           ▼ (only if PASS or CONDITIONAL_PASS)      │
│  PHASE 3: MOE EXPERT COUNCIL (Graph topology — all-to-all)          │
│  ──────────────────────────────────────────────────────────────     │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐                  │
│  │    BULL    │◄──│    BEAR    │──►│   QUANT    │                  │
│  │  ANALYST   │──►│  ANALYST   │◄──│  ANALYST   │                  │
│  └─────┬──────┘   └─────┬──────┘   └─────┬──────┘                  │
│        │                │                │                          │
│        └────────────────┼────────────────┘                          │
│                         ▼                                           │
│                  ┌─────────────┐                                     │
│                  │    MACRO    │ ← synthesizes all positions         │
│                  │ STRATEGIST  │ → writes SYNTHESIS_MEMO             │
│                  └─────────────┘                                     │
│                           │                                         │
│                [Writes: EXPERT_POSITIONS, SYNTHESIS_MEMO]           │
│                           │                                         │
│                           ▼                                         │
│  PHASE 4: REPORT GENERATION (Sequential, section by section)        │
│  ──────────────────────────────────────────────────────────────     │
│  REPORT-ORCHESTRATOR: reads verified data + synthesis memo,         │
│  writes 15 sections incrementally, updates SECTION_STATUS           │
│                           │                                         │
│                [Writes: 15 report sections, SECTION_STATUS]         │
│                           │                                         │
│                           ▼                                         │
│  PHASE 5: PRESENTATION LAYER (Parallel where independent)           │
│  ──────────────────────────────────────────────────────────────     │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ LATEX-         │  │   CHARTING   │  │   DIAGRAM    │            │
│  │ FORMATTER      │  │    AGENT     │  │    AGENT     │            │
│  └───────┬────────┘  └──────┬───────┘  └──────┬───────┘            │
│          │                  └──────────────────┘                    │
│          │                           │                              │
│          │              ┌────────────┘                              │
│          │              ▼                                           │
│          │   DATA-INTEGRITY-VIZ REVIEW                             │
│          │   (sequential: reviews all charts + diagrams)            │
│          │              │                                           │
│          └──────────────┘                                           │
│                          │                                          │
│              [All outputs fed to PDF compiler]                      │
│                           │                                         │
│                           ▼                                         │
│  PHASE 6: FINAL REVIEW GATE                                         │
│  ──────────────────────────────────────────────────────────────     │
│  PDF-REVIEWER: page-by-page review                                  │
│  Formatting / Content / Data / Compliance passes                    │
│  Gate: APPROVED / REVISE_AND_RESUBMIT                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Phase 0: Deterministic Pre-Flight

These steps require NO LLM judgment. Run them deterministically before invoking any agent.

```
Step 0.1 — Ticker Validation
  Input:  User-provided ticker string
  Action: Query exchange database for exact match
  Output: Verified ticker, exchange, ISIN (if available)
  Failure: Return error to user — do not proceed

Step 0.2 — CIK Resolution
  Input:  Verified ticker
  Action: Query SEC EDGAR CIK lookup API
          Endpoint: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=&CIK={ticker}&type=&dateb=&owner=include&count=40&search_text=
  Output: CIK (10-digit, zero-padded)
  Failure: Return CIK_NOT_FOUND — flag for SEC-EDGAR gatherer to retry

Step 0.3 — Market Status Check
  Input:  Current timestamp + exchange
  Action: Determine market hours status
  Output: OPEN / PRE_MARKET / AFTER_HOURS / CLOSED / WEEKEND
  Effect: Sets data_freshness_policy in ACE context

Step 0.4 — Filing Date Mapping
  Input:  CIK + fiscal year end
  Action: Determine most recent 10-K, 10-Q, 8-K filing dates
  Output: Filing date map (structured list, no agent needed)
  Purpose: All gatherer agents use this map — prevents duplicate EDGAR queries

Step 0.5 — Initialize ACE Context
  Action: Create empty ACE context document from ACE-CONTEXT-SCHEMA.md template
  Set:    ticker, CIK, analysis_date, market_status, filing_date_map
  Output: Initialized ACE context file ready for agent writes
```

---

## Phase 1: Parallel Data Gathering

**Rule:** All 5 gatherers launch simultaneously. They operate on independent data
streams. Do NOT serialize this phase. Latency compounds — parallelization here
directly determines total pipeline duration.

```
PARALLEL LAUNCH:
├── sec-edgar-gatherer    → EDGAR API (no dependency on other gatherers)
├── financial-data-gatherer → Bloomberg/FactSet/Refinitiv (independent)
├── sentiment-gatherer    → Reddit/StockTwits/X/Google (independent)
├── macro-gatherer        → Government/regulatory databases (independent)
└── catalyst-tracker      → Earnings calendar/IR page (independent)
```

Each gatherer:
1. Reads the initialized ACE context (ticker, CIK, filing dates)
2. Fetches its domain-specific data
3. Writes structured bullets to `ACE_CONTEXT.VERIFIED_DATA` with full metadata
4. Flags any items it cannot verify as `UNVERIFIED` in `ACE_CONTEXT.UNVERIFIED_FLAGS`
5. Signals completion to the orchestrator

**Gatherer completion policy:** The pipeline advances to Phase 2 when:
- ALL 5 gatherers signal completion, OR
- 4 of 5 complete and the remaining agent has timed out (>180 seconds)
- Timed-out agent's data section is marked `[GATHERER_TIMEOUT — PHASE 2 WILL FLAG]`

---

## Phase 2: Verification Gate

**The Integrator.** The source-verifier reads the complete VERIFIED_DATA from all
gatherers and performs cross-agent validation before any analyst sees the data.

**Gate Conditions:**

| Decision | Condition | Effect |
|---|---|---|
| PASS | All critical data fields present, <20% unverified flags, no unresolved CRITICAL conflicts | Proceed to Phase 3 |
| CONDITIONAL_PASS | 20-40% unverified flags, non-critical gaps, resolvable conflicts | Proceed to Phase 3 with UNVERIFIED_FLAGS visible to experts |
| BLOCK | Missing 10-K/10-Q, >40% critical fields unverified, CIK mismatch detected | Return to Phase 1 with specific re-fetch instructions |

**Critical data fields** (required for PASS):
- Basic share count (from most recent 10-Q cover page)
- Revenue (most recent fiscal year, audited)
- Total debt (most recent 10-Q)
- Filing dates for 10-K and most recent 10-Q
- At least 1 verified price data point

**The Distracting Effect (ACE research):** The verifier also applies distractor
filtering. It identifies data points that are:
- Semantically RELATED to the company but not directly RELEVANT (e.g., industry
  average data that was retrieved but doesn't apply to this specific company's
  business model)
- Modal statements ("The company may have exposure to...")
- Hypothetical scenarios presented as factual context

These are tagged `[DISTRACTOR_RISK]` and quarantined — they do NOT flow to Phase 3.

---

## Phase 3: MoE Expert Council

**Topology: Graph (all-to-all communication)**

Per multi-agent topology research: graph topology outperforms tree, chain, and star
for complex reasoning tasks. Each expert can read and respond to all others.

**Council Protocol:**

```
Round 1: Independent Analysis (parallel)
  Each expert reads VERIFIED_DATA + CONFLICT_LOG independently
  Each writes their initial position to EXPERT_POSITIONS[{role}]
  No reading other experts' positions in Round 1

Round 2: Debate (parallel with cross-reading)
  Each expert reads all other positions from Round 1
  Each writes rebuttals, agreements, or refinements as delta bullets
  Focus: where experts DISAGREE (these are the highest-value analytical moments)

Round 3: Synthesis (sequential — Macro Strategist only)
  Macro Strategist reads all Round 1 + Round 2 positions
  Writes SYNTHESIS_MEMO:
    - Base case: [description + probability %]
    - Bull case: [description + probability %]
    - Bear case: [description + probability %]
    - Key disagreements: [unresolved points flagged for reader]
    - Recommended price target range: [bear / base / bull]
```

**"Plan how to collaborate" step (improves milestone achievement +3%):**
Before Round 1, the orchestrator injects a brief Council Charter into each expert's
context: "Your role is [BULL/BEAR/QUANT/MACRO]. You are reading verified financial
data for {ticker}. In Round 2, specifically address the highest-conviction claim
from each other expert."

**Model selection for this phase:**
Use heavy reasoning models for the council (chain-of-thought budget required).
The quality of the SYNTHESIS_MEMO determines the quality of the entire report.
Do NOT optimize for speed in Phase 3.

---

## Phase 4: Report Generation

**Sequential. One section at a time.**

**Why sequential and not parallel?** Sections are NOT independent:
- Section II financial figures must be internally consistent with Section XIII DCF
- Section III share count must match Section XV game plan position sizing
- Section VIII risks must be addressed in Section XV exit triggers

The report-orchestrator writes sections in Roman numeral order (I → XV). Before
writing each section, it:
1. Pulls only the data relevant to that section from ACE context (context filtering)
2. Checks SECTION_STATUS for any prior sections' flagged inconsistencies
3. Writes the section and updates SECTION_STATUS[section_N] = COMPLETE
4. Does NOT rewrite completed sections — only appends to DELTA_LOG

**Context window management (ACE collapse prevention):**
Each section write uses a FILTERED context window — not the full ACE document.
The orchestrator requests only the VERIFIED_DATA bullets tagged for each section.
This prevents the context collapse phenomenon (18,282 tokens → 122 tokens) observed
when monolithic context is reprocessed repeatedly.

---

## Phase 5: Presentation Layer

**LaTeX and Charting/Diagrams are independent — run in parallel.**

```
PARALLEL:
├── latex-formatter  → Processes report sections into LaTeX markup
└── PARALLEL:
    ├── charting-agent   → Creates chart specifications from VERIFIED_DATA
    └── diagram-agent    → Creates structural/conceptual diagram specs

SEQUENTIAL (after charting + diagrams complete):
└── data-integrity-viz → Reviews ALL visual artifacts before PDF compilation
```

**Output artifacts:**
- `report.tex` (from latex-formatter)
- `charts/*.{py,json}` (from charting-agent — chart specs for rendering)
- `diagrams/*.mermaid` or `diagrams/*.tikz` (from diagram-agent)

**PDF compilation** is deterministic (no agent needed):
```
pdflatex report.tex
```
This runs after data-integrity-viz emits PASS on all visual artifacts.

---

## Phase 6: Final Review Gate

**The Reflector.** Per ACE research: must be separate from the Generator.
**Use a different model than report-orchestrator** — cross-model verification
catches blind spots that self-review misses.

**Review dimensions:**
1. Formatting (orphaned headers, broken tables, pagination)
2. Content consistency (cross-references, bibliography, in-text vs. chart figures)
3. Data integrity (all figures traceable to VERIFIED_DATA in ACE context)
4. Compliance (disclaimer footer, stale data flags visible, 15 sections complete)

**Gate output:**
- `APPROVED`: Zero CRITICAL, zero MAJOR issues → report is deliverable
- `REVISE_AND_RESUBMIT`: Issues list with severity + fix instructions → loop back
  to the specific agent responsible for the flagged content

**Re-entry points for REVISE_AND_RESUBMIT:**
- Formatting issues → latex-formatter
- Data inconsistency → report-orchestrator (DELTA_LOG entry only, no rewrite)
- Chart issues → data-integrity-viz loop
- Missing data → source-verifier (re-verify specific data point)

---

## ACE Context Flow Summary

```
WHO READS                    WHAT THEY READ              WHO WRITES
─────────────────────────────────────────────────────────────────────
Phase 0 (orchestrator)       [empty template]            ticker, CIK, dates, market_status

Phase 1 (all 5 gatherers)    ticker, CIK, filing_dates   VERIFIED_DATA bullets
                                                          UNVERIFIED_FLAGS

Phase 2 (verifier)           VERIFIED_DATA               CONFLICT_LOG
                             UNVERIFIED_FLAGS             DISTRACTOR_LOG
                                                          VERIFICATION_GATE_REPORT

Phase 3 (all 4 experts)      VERIFIED_DATA               EXPERT_POSITIONS[role]
                             CONFLICT_LOG                 SYNTHESIS_MEMO
                             DISTRACTOR_LOG (avoid)

Phase 4 (orchestrator)       VERIFIED_DATA (filtered)    SECTION_STATUS[I...XV]
                             SYNTHESIS_MEMO               DELTA_LOG

Phase 5 (presentation)       VERIFIED_DATA (charts only) chart specs, diagram specs
                             SECTION_STATUS               LaTeX source
                             report sections

Phase 6 (reviewer)           ALL sections                 REVIEW_GATE
                             ALL charts                   ISSUE_LIST
                             ACE context (data check)
```

---

## Model Selection Guidance

Per ACE research: different steps need different models. Optimize per phase.

| Phase | Agent | Recommended Model Type | Reasoning |
|---|---|---|---|
| 0 | Orchestrator | Deterministic (no LLM) | Rule-based validation |
| 1 | Gatherers | Fast, high-recall extraction | Speed + accuracy on structured data |
| 2 | Verifier | **Different from gatherers** | Cross-model verification benefit |
| 3 | Bull/Bear/Quant | Heavy reasoning model | Chain-of-thought debate required |
| 3 | Macro Strategist | Heavy reasoning + long context | Synthesis requires full council context |
| 4 | Report Orchestrator | High-quality prose generation | Output quality is user-facing |
| 5 | LaTeX/Chart/Diagram | Structured output specialist | Precision > creativity |
| 5 | Data-Integrity-Viz | Visual reasoning capability | Pattern detection in representations |
| 6 | PDF Reviewer | **Different from orchestrator** | Cross-model catches blind spots |

---

## Error Handling

| Error | Phase | Response |
|---|---|---|
| Invalid ticker | 0 | Return error immediately. Do not proceed. |
| CIK not found | 0 | Return error. Suggest EDGAR company search URL. |
| All gatherers timeout | 1 | BLOCK. Report which sources are unavailable. |
| Verifier BLOCK | 2 | Return specific re-fetch instructions. Do not proceed to Phase 3. |
| MoE council produces no synthesis | 3 | Orchestrator proceeds with raw EXPERT_POSITIONS; flags no synthesis. |
| Report section fails | 4 | Log to DELTA_LOG. Mark section FAILED. Continue to next section. |
| PDF compile error | 5 | Return LaTeX error to latex-formatter for correction. |
| Reviewer REVISE | 6 | Route issues to responsible agents. Re-run from specific phase. |

---

## Agent Files Reference

```
workflows/FinanceForge/
├── WORKFLOW.md                         ← This file
├── ACE-CONTEXT-SCHEMA.md               ← Context document specification
└── agents/
    ├── 01-gatherers/
    │   ├── sec-edgar.md                ← SEC EDGAR filing retrieval
    │   ├── financial-data.md           ← Financial statements + consensus
    │   ├── sentiment.md                ← Social sentiment + discovery
    │   ├── macro.md                    ← Macro + geopolitical + thematic
    │   └── catalyst-tracker.md         ← Events calendar + earnings dates
    ├── 02-verifier/
    │   └── source-verifier.md          ← Cross-validation gate (Integrator)
    ├── 03-moe-council/
    │   ├── bull-analyst.md             ← Long thesis + catalyst timing
    │   ├── bear-analyst.md             ← Short thesis + risk quantification
    │   ├── quant-analyst.md            ← DCF + ratio arithmetic arbiter
    │   └── macro-strategist.md         ← Macro context + synthesis author
    ├── 04-report/
    │   └── report-orchestrator.md      ← 15-section report generator
    ├── 05-presentation/
    │   ├── latex-formatter.md          ← Markdown → LaTeX conversion
    │   ├── charting.md                 ← Financial chart generation
    │   ├── diagram.md                  ← Structural diagram generation
    │   └── data-integrity-viz.md       ← Visual data integrity reviewer
    └── 06-review/
        └── pdf-reviewer.md             ← Final page-by-page PDF review
```

---

*FinanceForge Workflow v2.0*
*ACE Architecture — Agentic Context Engineering*
*Topology: Parallel gathering → Gate → Graph council → Sequential report → Parallel presentation → Gate*
