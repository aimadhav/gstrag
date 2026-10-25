# Chapter 7 source audit and fix verification

Historical audit recorded on 19 October 2026. **Update on 21 October:** both identified ingestion defects are repaired, targeted development regressions pass for hybrid, and frozen held-out scoring is complete. See [Experiment 02](EXPERIMENT_02_REPAIRS.md) for current status. Statements below about unfixed defects and unscored held-out retrieval describe the original audit state and are retained as evidence of what needed repair.

## Conclusion

The assistant read the entire supplied 45-page PDF as original-page renders and independently extracted text, including tables, footnotes, and diagrams. All 30 benchmark questions were audited for source support, scope, completeness, and acceptable alternatives on 19 October 2026.

The label audit is complete. **The ingestion issues are not fixed yet.** Two numbered subsection boundaries are wrong, and an image-only flowchart is not searchable. These must be repaired and checked before freezing the ingestion configuration. No explicit case structuring is needed.

This is an assistant source-faithfulness review, not independent legal validation, an expert answer assessment, or verification of current GST law. The chapter contains historical positions, competing rulings, author opinions, and subsequent qualifications; a source-faithful answer must distinguish them.

## What changed in the benchmark

The original draft labels and original result files were preserved. Revised labels are stored locally in `data/benchmark/chapter7_questions.source_audited_v2.json`, with a per-question audit note, supporting PDF page positions, and evidence scope. Original query text, IDs, development/held-out assignments, and expected behaviors were not changed.

- Sixteen questions received stronger evidence requirements, and one received equivalent-source alternatives without changing the required fact. Thirteen were retained after review.
- Required evidence groups increased from 37 to 58 across the 30 questions. Each group represents an independently required fact; alternatives within a group are interchangeable supporting excerpts.
- A full definition now requires its material conditions. An author's disagreement now requires the reasoning and proposed conclusion, not just a phrase saying the authority erred.
- Held-out labels were audited, but held-out retrieval was not scored. This is not an independent blind annotation exercise: the assistant had seen earlier development results.

For example, q01 previously rewarded retrieval of natural bundling alone. Its revised groups require a taxable person supplying a recipient, two or more taxable supplies, ordinary-course natural bundling, and a principal supply. Q04 now requires both predominance and the ancillary relationship. Q16 requires the table's parts-column meaning, the two parts values, and the author's repair-intention reasoning.

## Reassessment using identical saved development retrievals

Only the labels changed for this reassessment. The saved ranked hits, context text, 2,048-token budget, embeddings, and chunk configuration `749f74486094` were reused. No API requests or held-out retrieval were made. New filenames end in `_source_audited_v2.json`; earlier scores remain historical draft results.

| Method | Mean evidence recall at 5 | Mean evidence recall at 10 | Complete evidence at 10 | Mean context evidence recall |
|---|---:|---:|---:|---:|
| Fixed windows | 86.11% | 100% | 18/18 | 86.11% |
| Hierarchical | 87.50% | 94.44% | 17/18 | 94.44% |
| Hybrid | 100% | 100% | 18/18 | 100% |

The same hybrid rankings with neighboring context cover 94.44% of required evidence in the assembled context; parent expansion covers 100%, matching child-only context. Hierarchical still misses q05 at ten. Fixed windows lose required evidence for q04, q05, and q13 under the context budget; neighboring expansion loses q05.

Stronger labels need not lower every score. Adding independently required groups can award partial credit that the previous single group did not, and equivalent-source alternatives can recognize a valid earlier hit. Hierarchical recall at five rose from 83.33% to 87.50%, and hybrid MRR rose from 0.7917 to 0.8472 without any retrieval improvement. **These changes demonstrate a measurement correction, not a model improvement.** MRR here measures the first hit covering any required group, not complete evidence.

Hybrid remains a provisional development candidate. Its perfect evidence score on this small set does not cover the omitted diagram, all reversal scenarios, answer generation, or current-law accuracy.

## Findings requiring action

### Numbered subsection boundaries

PDF pages 14 and 17 contain headings numbered `7.2.10.` and `7.2.11.`. The heading recognizer expects whitespace immediately after the final digit. It misses the trailing-dot form in both depth restoration and numbered-parent selection. The current parent named 7.2.9 consequently spans PDF pages 12 through 19 and absorbs the solar and miscellaneous clarification sections.

Fix both recognition sites through one shared numbering helper. Test dotted and undotted headings, reject prose that merely mentions a section, and verify solar units belong to 7.2.10 and the subsequent clarification units to 7.2.11. Rebuild under a new configuration version in a separate artifact directory; do not relabel old metrics as results of the repaired pipeline.

### Image-only flowchart

PDF page 21 contains a summary flowchart represented as `#/pictures/1`. The diagram is not included in the current canonical units or searchable chunks. Covering all 285 canonical text/table source references therefore does not mean every meaningful PDF element was ingested.

For this resume project, a small reviewed diagram transcription associated with the original picture reference and page is sufficient. Check every node, branch condition, and outcome visually. Apply the same source addition to all chunking variants, then test that the evidence is actually retrievable and cited as page 21. This does not require enabling OCR for the entire book or building a vision subsystem.

### Later qualifications and competing authority

Keep the normal paragraph structure, but test whether retrieval includes the passages needed to qualify a position. Important examples include the later sharpener-rate note on page 22, Pattabi's AAR/AAAR contrast on page 29, Vertiv on pages 31-32, the reagent-contract court/remand discussion on pages 35-36, the DISCOM court discussion on page 40, and the shipping AAR/AAAR contrast on page 43.

The current benchmark underrepresents these reversal/qualification questions. Add a separate development stress set before the configuration is frozen. Do not inspect held-out retrieval to decide how to repair these failures. A narrow named-case question should report that case; a broader position/advice question requires the relevant later qualification too.

### Ambiguities within the source

Page 15 states the renewable-device change from 5% to 12% from 1 October 2021, but a following allocation paragraph still uses 5% without a clear time boundary. Page 32 prints both circular numbers 163/18/2021 and 163/19/2021. Record these as source ambiguities; do not silently select a number or rewrite a rate. External authoritative verification belongs to the later notification layer, not this source-only audit.

The author's room-rent objection on pages 36-37 and naturopathy disagreement on page 35 must not be presented as the ruling or as proof that a legal amendment was invalidated.

## How we prove the fixes work

| Check | Passing evidence | Current status |
|---|---|---|
| Source identity and coverage of review | Original PDF checksum agrees with parse and audited labels; review records cover all 45 pages | Checked |
| Evidence labels | Every alternative excerpt exists in its specified source; full question requirements were reviewed | Checked by assistant |
| Heading regression | Targeted unit tests plus rebuilt parent ownership for 7.2.10 and 7.2.11 | Not fixed |
| Diagram regression | Verified transcription, picture/page provenance, presence in every variant, and a retrieval question | Not fixed |
| Qualification regression | Development questions retrieve both original position and relevant later qualification where required | Not evaluated |
| Fair comparison | Same revised source, settings, embedding model, queries, and budget across all methods; versioned results | Pending repairs |
| Held-out evaluation | Freeze source, labels, and configuration, then run the ten held-out questions once without tuning on them | Not run |

Use these local checks now:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/verify_source_audit.py --require-ready
.venv\Scripts\python.exe scripts/rescore_source_audit.py
```

The readiness check intentionally exits unsuccessfully while the two known ingestion defects remain. It writes `data/audit/verification.json`. It is a structural/evidence check, not an automated legal reviewer. Existing contract tests are necessary, but cannot prove fixes for bugs they do not test.

After repairs, rebuild into a new directory and adapt the readiness check to inspect that directory. Confirm the old failure cases pass and prior valid cases still pass. Inspect misses rather than optimizing only a mean score. For the prototype, expect no missing required development evidence in the added targeted regression questions; report held-out retrieval misses honestly without treating 100% as a promised threshold.

When generation is added later, separately evaluate whether the answer includes each supported claim, cites the right page, labels opinion, refuses unsupported answers, and keeps high-risk drafts in admin review. Retrieval evidence coverage alone cannot verify those behaviors.

## Page review ledger

PDF positions 1 through 45 visually match the printed chapter labels 7.1 through 7.45. This is an audit observation; printed-label mapping has not been implemented in the ingestion code.

| PDF page | Content reviewed and relevant caution |
|---:|---|
| 1 | Chapter cover and first synopsis page; not substantive retrieval evidence. |
| 2 | Continued synopsis, introduction, and complete composite-supply definition. |
| 3 | Composite attributes, illustration, Section 8(a), and start of harmonious-construction argument. |
| 4 | Harmonious construction continued, Columbia Asia discussion, and natural-bundling indicators. |
| 5 | Indicators, no universal formula, examples, and start of online-exam discussion. |
| 6 | Exam discussion, furniture/accommodation/boarding/coaching examples, and departmental communication. |
| 7 | Principal-supply definition, ancillary relationship, and essential-character examples. |
| 8 | Video-conference contract, car package, earlier-regime analogy, and grey-area discussion. |
| 9 | Grey-area factors, immovable-property limit of works contract, and earthwork example. |
| 10 | Earthwork ruling with later dated rate notes; construction and networking examples. |
| 11 | Highway-lighting ruling with later note and start of dairy clarification. |
| 12 | Dairy classification and dated rates, Magnam author's disagreement, and start of ice-cream section. |
| 13 | Conflicting ice-cream rulings and later clarification; historical positions must be distinguished. |
| 14 | Sweetshop/restaurant and railway-food discussions; solar heading has a trailing dot. |
| 15 | Solar allocations and historical rate change; adjacent rate wording has unclear temporal scope. |
| 16 | Solar author notes, timing disputes, and interim court orders; interim orders are not final merits decisions. |
| 17 | Continued solar discussion and miscellaneous clarification heading with trailing dot; seed/GTA material begins. |
| 18 | GTA ancillary-service qualification, air transport, and mineral examples. |
| 19 | Mineral examples, mixed-supply definition and attributes, illustration, and highest-rate rule. |
| 20 | Independence, single-price distinction, and why non-composite does not automatically mean mixed. |
| 21 | Image-only summary flowchart, scrips, and ink example; the diagram is not searchable today. |
| 22 | Maintenance and sharpener discussions, later sharpener-rate note, repair qualification, and warranty note. |
| 23 | Repair table and author's intention-based reasoning; old judicial examples are contextual. |
| 24 | Repair qualification and separate-price circular discussion, separate orders, and tour packages. |
| 25 | Invoicing/contract examples including freight, hostel, Skipper, and start of BEML. |
| 26 | BEML continuation, construction/platform/insurance/DG-set examples, and author circular criticism. |
| 27 | Author criticism continued; chapter also says the circular is not withdrawn and binds the department. |
| 28 | Printing clarification table and initial printing cases; ownership/content/rights conditions matter. |
| 29 | Printing appeal distinction, bus-body cross-reference without local explanation, and retreading table begins. |
| 30 | Retreading table continued, value is not sole guide, supplier-owned tyres exception, and UPS discussion. |
| 31 | UPS/battery distinctions, author interpretation, and Vertiv AAR/appeal contrast. |
| 32 | Vertiv continued, inconsistent circular numbers, external-battery exception/rates, and desktop definition. |
| 33 | Desktop continued, inpatient/attendant distinction, and outpatient pharmacy reasoning. |
| 34 | Baroda Medicare and other inpatient/device cases, with separate occupational-health footnote qualification. |
| 35 | Naturopathy ruling versus author opinion and initial reagent-contract rulings. |
| 36 | Reagent-contract court/remand and supplier-identity reasoning, Randox, and room-rent amendment/opinion. |
| 37 | Room-rent opinion continued, promotional-goods competing views, and start of buy-one-get-one clarification. |
| 38 | Buy-one-get-one clarification, nominal-price promotion example, author's advice, and electricity cases begin. |
| 39 | Electricity cases; member disagreement means no advance ruling in one example; DISCOM table begins. |
| 40 | DISCOM table continued and court qualification; CIF/FOB descriptions are audited as book statements. |
| 41 | CIF composite-supply discussion and reported Mohit Minerals, Bhavani, and Agarwal Coal decisions. |
| 42 | Author CIF note, miscellaneous food/transport and milling cases. |
| 43 | Shipping AAR/AAAR contrast, windmills, removable AC, waste, and rail-welding examples. |
| 44 | Rail welding continued, parking and author comments, single-price distinction, and uncertainty. |
| 45 | Author comments continued on cases and classification complexity; no universal classification shortcut. |

## Reproducibility and boundaries

Source SHA256: `bddb8207104b9d462a85ecfab3e28ef0afbaa35f2b75add508131b3ca155ce96`.

The source PDF, extracted text, quote labels, and complete results remain local in ignored paths. Public project notes summarize the audit rather than redistribute the book. The independent PDF extraction used for reading is an audit aid; the ingestion pipeline remains Docling-based, not pdfplumber or pypdf-based. No source PDF was modified.
