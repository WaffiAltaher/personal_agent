# 10: Each tool describes its own Approval

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 09

**Status:** wontfix

**Closes:** (enables 16, 17)

**Why not:** it existed only for the upload's Approval (16, 17). The upload is now two plain Informer tools: a read check the agent calls first, and a Write action whose duplicate override is an explicit argument, so the Approval keeps today's name-and-arguments form and the graph holds no Informer-specific logic (grilling Q37; ADR-012 amendment).

**What it would have built:** A tool can provide a plain-language description of what its call will do, plus optional warnings, for the Approval. The Approval interrupt carries one entry per pending Write action with that description and any warnings; a tool without its own description falls back to its name and raw arguments (today's behaviour). The CLI shows the descriptions and warnings.

- [ ] Test through the graph seam: the interrupt payload carries a tool's own description and warnings
- [ ] Test: a tool without a description shows its name and raw arguments
- [ ] Test: a description that raises falls back to the raw form (the Approval must never fail to appear)
- [ ] Building the description has no side effects (the review step re-runs on resume)

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
