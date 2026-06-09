---
name: internal-comms
description: A set of resources to help me write all kinds of internal communications, using the formats that my company likes to use. Claude should use this skill whenever asked to write some sort of internal communications (status reports, leadership updates, 3P updates, company newsletters, FAQs, incident reports, project updates, etc.).
license: Complete terms in LICENSE.txt
---

# Internal Communications

## Output

**Always save the final output to `output.md`** using the Write or file-write tool. Do not only print to chat — the result must exist as a file named `output.md` in the current directory.

---

## Communication Types & Formats

### 3P Updates (Progress / Plans / Problems)

**When to use:** Weekly team updates sent to leadership, executives, and teammates.

**Audience:** People with some but not full context on the team. Should be readable in 30–60 seconds.

**Format (strict — never deviate):**

```
[emoji] [Team Name] ([Date range, e.g. May 5–9, 2026])
Progress: [1–3 sentences. What shipped, milestones hit, tasks completed.]
Plans: [1–3 sentences. What's top priority for next week.]
Problems: [1–3 sentences. Blockers, staffing gaps, risks.]
```

**Rules:**
- Pick an emoji that fits the team's vibe
- Each section = 1–3 sentences max, data-driven, include metrics where possible
- Never use bullet points — only sentences
- If team name not provided, ask before writing
- Do NOT invent facts not given in the prompt

---

### Company Newsletter

**When to use:** Company-wide weekly or monthly summary sent via Slack and email.

**Audience:** Entire company (1000+ people). Accessible, celebratory tone.

**Format:**

```markdown
:megaphone: Company Announcements
- [1–2 sentence bullet with link if available]
- ...

:dart: Progress on Priorities
- Area 1
  - Sub-item
- Area 2
  - Sub-item

:pillar: Leadership Updates
- [key exec posts, decisions, announcements]

:thread: Social Updates
- [press, external recognition, community]
```

**Rules:**
- 20–25 bullets total, broken into sections
- Each bullet ≤ 2 sentences
- Use "we" tense ("we shipped", "we hired")
- Include links where naturally appropriate (use placeholder `[link]` if URL not provided)
- Focus on company-wide impact, not team-specific detail
- Do NOT invent facts not given in the prompt

---

### FAQ Answers

**When to use:** Answering frequently asked employee questions about company-wide topics.

**Audience:** All employees.

**Format:**

```
- *Question*: [1 sentence question]
- *Answer*: [1–2 sentence answer]
```

**Rules:**
- Pair each question with a concise answer
- Base answers on facts provided in the prompt
- If uncertain, say "This has not been officially confirmed"
- Do NOT invent facts not given in the prompt

---

### General / Other Comms

**When to use:** Anything that doesn't fit 3P, newsletter, or FAQ — status reports, incident reports, leadership updates, project updates, office announcements, etc.

**Before writing, identify:**
1. Target audience (executives? all-hands? specific team?)
2. Purpose (inform, reassure, escalate, celebrate?)
3. Required tone (formal, urgent, casual, informational)

**Format principles:**
- Put most important information first
- Active voice, short sentences
- Use headers for multi-section documents
- Match the formality to the audience

---

## Common Mistakes

1. **Writing to chat instead of saving to `output.md`** — Always write the final output to `output.md`. Chat responses are not captured by the pipeline.

2. **Inventing facts** — Only use information provided in the prompt. Do not hallucinate metrics, names, or events.

3. **Wrong 3P format** — 3P uses sentences, not bullet points. Three sections only: Progress, Plans, Problems.

4. **Newsletter too long or too short** — Target 20–25 bullets. Fewer than 15 or more than 30 is wrong.

5. **FAQ answers too long** — Each answer must be 1–2 sentences max.

6. **Missing team name in 3P** — If not specified, ask before writing. Never invent a team name.
