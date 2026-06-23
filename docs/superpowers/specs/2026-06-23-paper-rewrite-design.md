# Specification: Overwriting Paper Draft for Language-Level Skill Distillation

**Date:** 2026-06-23
**Status:** Approved
**Target File:** `docs/thesis/paper/paper_draft.md`

## 1. Goal
Overchange and rewrite the current paper draft at `docs/thesis/paper/paper_draft.md` to elevate its academic rigor, integrate necessary mathematical formalizations, and expand its depth by approximately 2x. The target paper will be formatted in clean, academic Markdown suitable for conversion to LaTeX or Word, written entirely in formal scientific English.

## 2. Structural Restructuring Plan

We will expand the current sections as follows:

1.  **Title**: Update to a more active, method-oriented title:
    *   *Language-Level Skill Distillation: Optimizing Agentic Procedural Knowledge for Small Language Models*
2.  **Abstract**:
    *   Rewrite to clearly articulate the problem of performance mismatch (negative transfer) when executing frontier-authored skill documents on SLMs.
    *   Summarize the Teacher-Student-Judge optimization framework, quantitative results (+17% relative gain), and core implications.
3.  **Introduction**:
    *   Provide a deeper explanation of the "Skill Portability Problem" and why instruction-following is fragile in SLMs (under 30B parameters).
    *   Highlight the motivating anomaly: Gemma-4-26B's performance *degradation* when using the original skill documents compared to the zero-shot "No-Skill" baseline.
    *   Enumerate concrete contributions with academic authority.
4.  **Background & Related Work**:
    *   Discuss Agent Skills (progressive disclosure levels L1, L2, L3) and differentiate them from single-turn system prompts and tools.
    *   Create a taxonomy table comparing APE, OPRO, Self-Refine, Reflexion, SkillOpt, and our framework across dimensions of search space, feedback loop, evaluation method, and target model weight updates.
    *   Position the work as "Symbolic, non-differentiable prompt optimization at the document scale" (parameter-free distillation).
5.  **Methodology**:
    *   Formally define the mathematical optimization problem of finding $M^*$ that maximizes the expected score over test cases $T$.
    *   Introduce formal equations for the weighted rubric scoring mechanism, the median ensemble of the Judge, the candidate validation Gate 1, and the round-level rollback Gate 2.
    *   Include a formatted academic Pseudocode block (`Algorithm 1: Teacher-Student-Judge Skill Document Optimization`) showing the complete iterative loop.
6.  **Experimental Setup**:
    *   Provide details on the three test skills (`docx`, `internal-comms`, `slack-gif-creator`), the test cases (76 total), and the five workflow categories (Create, Read, Edit, Convert, Edge).
    *   Detail the runtime parameters and LLM configurations (Gemma-4-26B as Student, Claude-Haiku-4.5 as Teacher and Judge).
7.  **Results & Evaluation**:
    *   Present quantitative results tables (mean scores, absolute and relative gains, peak rounds).
    *   Deeply analyze the "No-Skill" vs. "Original Skill" vs. "Optimized Skill" baseline to dissect negative transfer.
    *   Add a qualitative analysis section containing case studies of the rewritten rule changes made by the Teacher (e.g., adding explicit constraints, postcondition validation calls, and error-handling steps).
    *   Discuss the convergence dynamics, non-monotonicity, and late-round overfitting behavior.
8.  **Discussion & Limitations**:
    *   Analyze the theoretical ceiling of language-level optimization.
    *   Directly address "Self-Preference Bias" of LLM-as-Judge when utilizing the same model family for Teacher and Judge.
    *   Outline structural limits like context windows, execution timeouts, and student parametric capacities.
9.  **Conclusion**:
    *   Reiterate key findings and list structured avenues for future research (e.g., cross-model transferability, zero-temperature judging, human-in-the-loop evaluation).

## 3. Mathematical Formulations to Include

*   **Objective Function**:
    $$M^* = \arg\max_{M} \frac{1}{|T|} \sum_{t \in T} Q(\text{Student}(M, t), \text{Rubric}_t)$$
*   **Next-Round Generation**:
    $$M_{r+1} = \text{Teacher}(M_r, F_r)$$
    where $F_r$ represents the summarized failure feedback accumulated by the Reflexion-style Summarizer.
*   **Weighted Scoring**:
    $$o = \sum_{i=1}^K w_i \cdot s_i \quad \text{s.t.} \quad \sum_{i=1}^K w_i = 1$$
*   **Median Ensemble**:
    $$q(t) = \text{median}\left\{ o^{(1)}, o^{(2)}, \dots, o^{(N)} \right\}$$
*   **Gate 1 (Validation)**:
    $$S_{val} \ge S_{base} - \tau_1$$
*   **Gate 2 (Rollback)**:
    $$\text{If } S_r - S_{r-1} < -\tau_2 \implies M \gets M_{best}$$

## 4. Verification Check
- Verify that all numbers match the stable experimental runs reported in the thesis (e.g., `docx` peak 0.921, `internal-comms` peak 0.823, `slack-gif-creator` peak 0.886).
- Ensure references are correctly formatted in an academic BibTeX style or numbered list.
