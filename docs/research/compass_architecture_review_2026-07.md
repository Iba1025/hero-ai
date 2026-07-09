# Hero.AI Technical Architecture Review: Prioritized Recommendations for a Pre-Seed Property-Maintenance Diagnostic OS

## TL;DR
- **The current four-plane architecture is well-designed and ahead of the curve for a pre-seed company; the single highest-leverage change is adding a cross-encoder reranker and a corrective/agentic retrieval loop to the knowledge plane, while retaining the grounded VERIFY state — these directly move diagnostic accuracy. Most of the intern's proposals are premature optimization.**
- **Of the 8 proposals: keep BM25 (do NOT swap for ColBERT — it breaks exact SKU/part-number matching), shift calibration to Platt/temperature scaling now in the small-data regime, adopt conformal prediction at the SAFETY_GATE (genuinely valuable and cheap), and adopt DuckDB-over-Parquet for analytics. Defer PILLM, time-series BMS ingestion, domain fine-tuning, and the Neo4j parts-compatibility graph.**
- **The "LightLLM4FDD / 99.8%" claim is unsubstantiated — no such paper exists. The real source is a GPT-3.5 fine-tune (Zhang, Zhang, Lu & Zhao 2025, *Applied Energy* vol. 377, p. 124378) that rose "from 29.5% to 100.0%" on the clean single-AHU RP-1312 benchmark and to 99.1%/98.9% on the two LBNL AHUs — controlled, single-equipment datasets that are not comparable to Hero.AI's 91% real-world multimodal multi-trade accuracy. Domain fine-tuning is a long-term moat blocked by a cold-start data problem, not a quick win.**

## Key Findings

1. **The control plane (LangGraph + Postgres checkpointer) is current best practice.** A deterministic state machine with checkpointing for resumable, human-in-the-loop runs is exactly the pattern LangChain's Self-Reflective/Corrective RAG tutorials are built on, and the 2025 Agentic RAG survey (Singh et al., arXiv:2501.09136) formalizes corrective/adaptive patterns as the state of the art. No change needed; this is a strength.

2. **The knowledge plane is sound but missing two cheap, high-impact components: a cross-encoder reranker and a corrective retrieval loop.** ColQwen2.5-7B + multi-vector MaxSim in Qdrant + BM25 + RRF is a genuinely state-of-the-art visual-document RAG stack. The literature consistently shows that adding a cross-encoder reranker on top of hybrid retrieval is the single most reliable accuracy lever, and that corrective/agentic RAG (CRAG) adds meaningful gains on hard queries.

3. **Replacing BM25 with ColBERT (Proposal 1) is a mistake for this use case.** ColBERT does soft, semantic token matching — it does not preserve guaranteed exact-token matching, which is precisely what you need for SKU codes and part numbers. It also costs an order of magnitude more in storage (one vector per token) and indexing complexity. BM25's exact-match property is a feature, not a bug, here.

4. **The "99.8% HVAC fine-tune" claim is fabricated or conflated.** The closest real paper is a GPT-3.5 fine-tune on clean single-system AHU benchmarks. These numbers are not comparable to real-world multi-trade accuracy.

5. **Conformal prediction at the SAFETY_GATE (Proposal 3) is the most underrated proposal** — it gives distribution-free, statistically guaranteed coverage and is cheap to implement, fitting the hazard-escalation logic perfectly.

6. **Verbalized model confidence is genuinely poorly calibrated and sycophantic** — the PRD's decision to use grounded VERIFY rather than raw model confidence is well-supported by the literature and should be retained and strengthened.

## Details

### Plane-by-plane best-practice assessment

**Control/orchestration plane.** The LangGraph deterministic state machine with a Postgres checkpointer for resumable runs and HITL is current best practice for high-stakes agentic workflows. LangChain's Self-Reflective RAG and Corrective RAG reference implementations are built on exactly this checkpointing substrate, and the 2025 Agentic RAG survey (Singh et al., arXiv:2501.09136) formalizes corrective/adaptive patterns as state of the art. Keep as-is. The one enhancement worth making is to make the RETRIEVE→CLARIFY→DIAGNOSE loop *corrective*: grade retrieved evidence and re-retrieve/rewrite if it is insufficient before diagnosing.

**Knowledge/RAG plane.** ColQwen2.5-7B is described in 2026 production guides as "the right starting point" for multimodal document RAG, with top ViDoRe retrieval accuracy and strong mixed-language handling. For calibration of expectations: the original ColPali reported ~81.3 nDCG@5 on ViDoRe, current SOTA models surpass 90 nDCG@5, and ColQwen achieves around 90 nDCG@5 (Hugging Face ViDoRe V2; REAL-MM-RAG, arXiv:2502.12342). The multi-vector late-interaction approach preserves diagram/layout information without OCR, which is ideal for manufacturer manuals. Two gaps:
- **Add a cross-encoder reranker.** Multiple 2025 studies report large precision gains from reranking top-k hybrid candidates (retrieve ~50–100, rerank to ~10). The size of the prize is illustrated by visually-rich documents specifically: on financial PDFs, dense text-only recall is ~62% versus ~84% with ColQwen (Spheron, 2026) — reranking closes a meaningful slice of remaining error. Self-hosted ms-marco-MiniLM-class cross-encoders are cheap and Canadian-residency-compatible; Cohere Rerank is stronger but is a third-party API (residency concern). This is the single highest-ROI retrieval change.
- **Add a corrective retrieval loop (CRAG-style).** A lightweight evaluator grades whether retrieved manual pages actually support the hypothesis, triggering re-retrieval when they don't. CRAG-style methods reported double-digit accuracy improvements on hard multi-hop QA, at ~1.5x latency for simple queries.
- **Storage note (concrete cost lever):** multi-vector ColQwen embeddings are storage-heavy (~100KB–500KB index per page at float32; ~100–500GB per 1M pages). Per the Spheron 2026 guide, "int8 scalar quantization is nearly lossless for retrieval quality (typically less than 1% nDCG@5 degradation) while cutting storage and bandwidth requirements by 4x"; binary quantization (per Vespa) cuts ~32x with a larger but often acceptable accuracy hit. Use on-disk Qdrant indexing for large corpora.

**Procurement/entity-resolution plane.** The current dense+BM25 → synonym expansion → rerank → SKU-lock pipeline aligns with 2025 entity-matching best practice (multi-signal: embeddings + ANN + deterministic exact signals). The crucial design point: **keep exact-match (BM25/deterministic) signals for part numbers and SKU codes** — this is where ColBERT would actively hurt. The undecided SKU-catalog source is the real risk; entity-resolution quality is bounded by catalog quality. A cross-encoder or LLM reranker on the final candidate set is a reasonable enhancement.

**Case/storage plane.** Media bytes in R2/S3 with presigned direct/multipart upload, plus structured records + pointers in Postgres, is textbook and correct. No change.

**Verification + calibration plane.** Grounding VERIFY against retrieved evidence rather than raw model confidence is strongly supported: verbalized LLM confidence is empirically miscalibrated and overconfident, RLHF amplifies this, and models are demonstrably sycophantic under contradiction (2026 robustness studies show Claude Sonnet's accuracy collapsing under explicit contradiction). For post-hoc calibration:
- **Isotonic vs Platt:** The classic Niculescu-Mizil & Caruana (ICML 2005, "Predicting Good Probabilities With Supervised Learning") result is direct: "When there are 1000 or more points in the calibration set, Isotonic Regression always yields performance as good as, or better than, Platt Scaling," and isotonic "is easier for it to overfit when the calibration set is small." In Hero.AI's small-data, pre-seed regime, Platt scaling (or temperature scaling) is the more defensible default, transitioning to isotonic as ContractorStatement data accumulates past ~1000 confirmed outcomes. Per-system-type (adaptive) temperature is reasonable once there is enough per-domain data; don't fragment a small dataset prematurely.

**Safety plane.** Mandatory VERIFY before SAFETY_GATE with always-escalate rules for gas/high-voltage/structural/water hazards is correct and should never be gated on confidence. Conformal prediction (below) strengthens this.

**Observability plane.** Self-hosted Langfuse satisfies Canadian residency and ships LLM-as-judge evaluators (Ragas-backed) for faithfulness/hallucination. Keep, and use it to build an offline eval harness.

**Model routing.** Claude Sonnet primary / GPT-4o fallback through LiteLLM for cost arbitrage, failover, and token logging is a sensible pre-seed pattern. Keep.

**Data flywheel.** ContractorStatement ⋈ Diagnosis as labeled-outcome signal is the right long-term moat. The DuckDB recommendation (below) concerns *where* to run these joins.

### Evaluating the 8 proposals

**Proposal 1 — Replace BM25 with ColBERT: REJECT.** ColBERT does soft semantic matching that is most active on low-IDF/contextual tokens; it does not guarantee exact-token matching. For SKU codes/part numbers, exact string match IS the signal, and BM25/inverted indexes deliver it in single-digit milliseconds at trivial cost. ColBERT inflates storage by ~an order of magnitude (one vector per token) and adds ANN-indexing complexity — not a drop-in, and the wrong tool. Note: late interaction already exists in your stack via ColQwen, so you are not missing the technique.

**Proposal 2 — Platt now → Adaptive Temperature Scaling later: SOUND, better than current default.** In the small-data regime Platt scaling is genuinely more appropriate than isotonic (which overfits below ~1000 points per Niculescu-Mizil & Caruana). Temperature scaling (Guo et al. 2017) is the simplest, most robust starting point for neural/LLM logit outputs and "outperforms all other methods on the vision tasks." The migration plan is reasonable. Caveat: per-system-type temperature requires enough data per system type; start global, specialize later. Keep tracking ECE.

**Proposal 3 — Conformal prediction at SAFETY_GATE: ADOPT.** This is the strongest proposal. Conformal prediction provides distribution-free, finite-sample coverage guarantees (true label in the set with probability ≥ 1−α) under exchangeability (Vovk et al. 2005; Angelopoulos & Bates 2021), requiring only a modest calibration set. For hazard categories, outputting a guaranteed-coverage prediction set — and escalating whenever the set is non-singleton or contains a hazard — is exactly the right safety primitive. Cheap, theoretically grounded, and aligned with existing escalation logic. Caveat: coverage holds marginally and assumes exchangeability; distribution shift (new building/equipment types) degrades the guarantee, so monitor and re-calibrate.

**Proposal 4 — Physics-Informed LLM (PILLM) constraints at VERIFY: DEFER (selectively useful later).** PILLM is a real 2025 method (Hua et al., arXiv:2510.17146) but it generates HVAC anomaly-detection *rules* in an evolutionary loop — it is not a general thermodynamics/circuit-law validator you can drop into VERIFY. The genuinely useful, cheap version is deterministic sanity-check rules (e.g., a part's voltage/phase must match the panel; a refrigerant must match the system) as hard filters — but that is a rules engine, not PILLM. Full physics-informed reasoning is over-engineered for pre-seed.

**Proposal 5 — Domain fine-tune (the "LightLLM4FDD 99.8%" model): DEFER; claim is overstated.** No model by that name exists in the indexable literature. The real reference is Zhang, Zhang, Lu & Zhao 2025 (*Applied Energy* vol. 377, p. 124378), a **GPT-3.5** fine-tune (not Llama-3-8B) compared against **GPT-4** (not GPT-4o; no DeepSeek-V3 baseline). Its accuracy rose "from 29.5% to 100.0% after fine-tuning" on RP-1312, and on the held-out LBNL set "from 46.0% to 99.1%" (single-duct AHU) and "from 38.8% to 98.9%" (dual-duct AHU); VAV box "from 33.0% to 98.3%" and chiller plant "from 36.0% to 99.1%." Every one of these is a clean, controlled, single-equipment AHU/VAV/chiller benchmark with a handful of fault classes — categorically not comparable to 91% on real-world, multimodal, multi-trade faults. Fine-tuning also faces a cold-start data problem: there is no public real-world labeled multi-trade dataset (corroborated by the FDD-dataset literature noting "no publicly available raw and labeled data for real operational faults in AHUs"), and the flywheel has not accumulated enough labels yet. Fine-tuning is a plausible long-term moat once ContractorStatement data is large, but it is not a near-term accuracy lever and the headline number is misleading.

**Proposal 6 — Time-series BMS data serialized as text at INTAKE: DEFER.** The literature is clear that naive time-series-to-text serialization fails on long sequences and subtle/complex anomalies; LLMs underperform specialized models, and Llama-3-8B's ~4096-token context truncates high-frequency data (one day at one-minute intervals is 1,440 points). If BMS data is valuable, the right pattern is a small specialized time-series encoder/feature-extractor feeding a compact summary into the LLM — not raw serialization. Premature for pre-seed; revisit when a design partner has accessible BMS telemetry.

**Proposal 7 — Neo4j parts-compatibility Graph RAG: DEFER (compelling long-term).** A compatibility graph (voltage/RPM/frame/rotation) is genuinely the right model for enforcing hard procurement constraints, and GraphRAG is mature in 2025 (Edge et al. 2024; Neo4j GraphRAG Python; Qdrant+Neo4j hybrid patterns). But standing up and, critically, *populating* a graph DB with accurate compatibility data is heavy for a pre-seed team, and the same constraints can be enforced now with a relational compatibility table + deterministic filters in Postgres. Build the rules first; graduate to a graph when the compatibility relationships outgrow SQL.

**Proposal 8 — DuckDB now → BigQuery/Snowflake later: ADOPT (DuckDB), DEFER warehouse.** Separating analytical flywheel queries from operational Postgres is correct best practice — Postgres is row-oriented OLTP, and analytical scans cause noisy-neighbor contention. DuckDB over Parquet (or querying Postgres directly via the postgres_scanner / a read replica) gives ~90% of warehouse benefits at ~10% of cost for a single-node team, with no per-query charges (MotherDuck, Definite, Crunchy Data). A cheap, sensible win. Hold off on BigQuery/Snowflake until data volume genuinely exceeds single-node scale (typically 100GB+).

### What the intern missed
- **Cross-encoder reranking** — the highest-ROI retrieval upgrade, omitted entirely.
- **Corrective/agentic RAG (CRAG/Self-RAG)** — self-grading retrieval, directly relevant to a diagnosis loop.
- **Structured output / constrained decoding** for safety-gate outputs — guarantees schema compliance (but note: schema-valid ≠ semantically correct; don't over-trust it, and be aware constrained decoding can be a jailbreak surface).
- **LLM-as-judge eval harness** in Langfuse for offline regression testing of diagnostic accuracy (human–judge agreement of ~90–98% is reported across recent studies — a usable proxy if validated).
- **Int8/binary quantization** of ColQwen embeddings — a concrete near-term cost lever.
- **Retrieval evaluation methodology** (recall@k, nDCG@5) to actually measure whether retrieval changes help.

## Recommendations

**Quick Wins (weeks; low effort, high impact):**
1. **Add a self-hosted cross-encoder reranker** (ms-marco-MiniLM class) on top of hybrid retrieval. Retrieve ~50–100, rerank to ~10. Biggest single accuracy lever; keep it Canadian-resident.
2. **Add a corrective retrieval loop** in LangGraph: grade retrieved manual evidence; re-retrieve/rewrite query if insufficient before DIAGNOSE. Cap with a latency timeout and fall back to one-shot retrieval.
3. **Switch default calibration to Platt/temperature scaling** while the calibration set is small (<~1000 confirmed outcomes); keep isotonic staged for when data grows. Continue tracking ECE.
4. **Int8-quantize ColQwen embeddings** and move Qdrant to on-disk indexing — immediate storage/cost reduction with <1% nDCG@5 loss.
5. **Build an LLM-as-judge eval harness in Langfuse** (faithfulness/grounding) so every change is measured against a fixed diagnostic test set.

**Medium-term (1–2 quarters):**
6. **Adopt conformal prediction at the SAFETY_GATE** for hazard categories: output guaranteed-coverage prediction sets; escalate on non-singleton or hazard-containing sets. Monitor coverage under distribution shift.
7. **Stand up DuckDB-over-Parquet (or postgres_scanner on a read replica)** for flywheel analytics, separating them from operational Postgres.
8. **Implement deterministic procurement hard-filters** (voltage/phase/refrigerant/frame) as a relational compatibility table — captures ~80% of Proposal 7's value cheaply.
9. **Lock down the SKU-catalog source** — entity-resolution quality is bounded by catalog quality; this is the procurement plane's real bottleneck.

**Long-term (post-Series-A / data-rich):**
10. **Revisit domain fine-tuning** once the ContractorStatement flywheel has thousands of labeled real-world outcomes — as a moat, not an accuracy quick-fix.
11. **Graduate the compatibility rules to a graph DB** (Neo4j/FalkorDB/Memgraph) if relationships outgrow SQL.
12. **Revisit BMS time-series** via a specialized time-series encoder feeding summaries to the LLM — not raw text serialization.
13. **Consider a cloud warehouse** (BigQuery/Snowflake) only when single-node DuckDB is genuinely exceeded.

**Benchmarks that would change these recommendations:** if the calibration set exceeds ~1000 confirmed outcomes → switch to isotonic; if retrieval recall@10 is already >95% on a held-out manual set → reranker ROI drops and focus shifts to reasoning/verification; if a design partner provides a large labeled BMS/multi-trade dataset → fine-tuning and time-series ingestion move up.

### What will actually move accuracy beyond 91% vs premature optimization
**Will move the needle:** reranking + corrective retrieval (better evidence → better grounded diagnoses); a real eval harness (you can't improve what you don't measure); SKU-catalog quality; retaining grounded VERIFY over model confidence. **Premature optimization:** domain fine-tuning (cold-start data problem, misleading benchmark), PILLM physics reasoning, BMS time-series serialization, and a Neo4j graph — all defer-worthy. ColBERT-for-BM25 is not optimization at all; it's a regression for SKU matching.

## Caveats
- The "LightLLM4FDD / 99.8% / beats GPT-4o & DeepSeek-V3" claim could not be verified and appears fabricated or conflated with the Zhang et al. 2025 GPT-3.5 paper on clean single-AHU benchmarks; treat as unsubstantiated.
- Conformal prediction's coverage guarantee is marginal and assumes exchangeability; new building/equipment types violate this and degrade the guarantee — monitor and re-calibrate.
- Cross-encoder reranking and corrective loops add latency; budget for timeouts/fallbacks.
- Many cited improvement percentages (reranking "+33–40%", CRAG "+12–18%") are benchmark-specific (often text-QA datasets), not property-maintenance data; treat as directional and validate on your own eval set.
- Structured/constrained decoding guarantees format, not correctness — do not let schema-valid outputs bypass grounded verification.
- Several sources are vendor blogs (Qdrant, Weaviate, MotherDuck, Spheron, Definite); their directional claims are corroborated by peer-reviewed work, but their cost/performance figures may be optimistic.