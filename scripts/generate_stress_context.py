#!/usr/bin/env python3
"""
scripts/generate_stress_context.py

Generates worst-case context fixtures for context-pressure testing.
Produces three JSON files in tests/fixtures/:

  long_conversation.json      — 30 HumanMessage/AIMessage pairs (~200 words each)
  bloated_tool_result.json    — 25 fake emails (subject + sender + date + 150-word body)
  large_memory_injection.json — 15 MemoryChunk-like dicts (~300 words, scores 0.95→0.61)

Run manually:
  python scripts/generate_stress_context.py

Also callable from tests via generate_all().
"""

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

# ---------------------------------------------------------------------------
# Fixture data — realistic work/productivity content, not lorem ipsum
# ---------------------------------------------------------------------------

_CONVERSATION_PAIRS = [
    (
        "Can you pull up my calendar for next Monday and summarize the meetings I have?",
        "Sure. You have three meetings on Monday: a 9 AM sprint planning with the platform team "
        "(1 hour), a 1 PM architecture review for the data pipeline migration (90 minutes), and "
        "a 4 PM 1-on-1 with your manager. The sprint planning has a pre-read doc attached — do "
        "you want me to summarise that as well? The architecture review agenda mentions discussing "
        "the transition from Postgres to a hybrid Postgres/ClickHouse setup for analytics queries. "
        "Your manager 1-on-1 has no agenda set yet. Total meeting time: 3.5 hours, leaving roughly "
        "2 hours of focus time in the morning and a short gap between the architecture review and "
        "the 1-on-1.",
    ),
    (
        "What are the open action items from last week's sprint retrospective?",
        "Based on the retrospective notes I found, the open action items from last week are: "
        "(1) Update the on-call runbook to include the new authentication service failure modes — "
        "owner: Alex, due Friday. (2) Add latency SLO dashboards for the recommendation API — "
        "owner: Priya, due end of sprint. (3) Schedule a dedicated post-mortem for the Tuesday "
        "outage — owner: you, no due date set yet. (4) Migrate remaining integration tests from "
        "the deprecated test runner to pytest — owner: the whole team, tracked in JIRA DF2LPE-441. "
        "(5) Document the data retention policy for user event logs — owner: Marcus, in progress. "
        "Three of the five items have no progress update in the ticket system yet.",
    ),
    (
        "Search my email for anything from the legal team this week.",
        "I found four emails from the legal team this week. The first, sent Monday, is a reminder "
        "that all vendor contracts over $50k require a secondary review before Q3 close — action "
        "needed by you if any new vendor agreements are pending. The second, sent Tuesday, is a "
        "response to your data processing agreement question: they confirmed the DPA template has "
        "been updated to reflect the new EU AI Act provisions. The third, sent Wednesday, flags "
        "that the open-source licence audit is due next Friday — they've attached a checklist. "
        "The fourth, sent today, is a calendar invite for a 30-minute sync about the security "
        "disclosure process. Do you want me to draft a reply to any of these?",
    ),
    (
        "What did the on-call engineer report during this week's incident?",
        "The on-call report filed by Jaime covers the incident on Tuesday evening. The alert "
        "triggered at 21:14 UTC when error rates on the payment service exceeded 5% for more than "
        "three minutes. Root cause was a misconfigured feature flag that enabled a new retry "
        "policy in production before it had been load tested — the retries amplified traffic and "
        "saturated the database connection pool. Mitigation was rolling back the feature flag at "
        "21:29 UTC; error rates returned to baseline within four minutes. Total user-facing "
        "impact window: approximately 19 minutes. Three follow-up tickets were filed: connection "
        "pool sizing review, feature flag rollout checklist update, and a load test requirement "
        "for all retry policy changes. Jaime's MTTR was within SLA.",
    ),
    (
        "Can you draft a status update for the data pipeline project to send to stakeholders?",
        "Here is a draft status update for the data pipeline migration project:\n\n"
        "Subject: Data Pipeline Migration — Week 18 Status Update\n\n"
        "Team, quick update on where we stand with the pipeline migration:\n\n"
        "Progress: The ingestion layer is fully migrated and has been running in production for "
        "two weeks without issues. The transformation layer is 70% complete; remaining work is "
        "the currency normalisation and late-arrival event handling modules.\n\n"
        "Blockers: We're waiting on the data warehouse team to provision the new ClickHouse "
        "cluster. This is on track for Thursday. No action needed from stakeholders.\n\n"
        "Risks: The end-to-end latency target of sub-5-minutes for hourly aggregates may be "
        "challenging if ClickHouse provisioning slips. We have a mitigation plan ready.\n\n"
        "Next milestone: Full transformation layer in staging by next Wednesday. Let me know if "
        "you'd like any changes before I send this.",
    ),
    (
        "What JIRA tickets are assigned to me and due this sprint?",
        "You have six tickets assigned to you in the current sprint (Sprint 34). In progress: "
        "DF2LPE-502 (implement rate limiting middleware, story points: 5) and DF2LPE-517 "
        "(refactor authentication token storage to meet compliance requirements, 8 points). "
        "To do: DF2LPE-524 (add unit tests for the new retry logic, 3 points), DF2LPE-531 "
        "(update API documentation for the v2 endpoints, 2 points), and DF2LPE-537 (investigate "
        "slow query on the user preferences table, 3 points). Blocked: DF2LPE-498 (migrate "
        "legacy batch jobs to the new scheduler) — blocked on infrastructure access from DevOps. "
        "Total committed points: 21. Sprint velocity target: 24. You're slightly under capacity.",
    ),
    (
        "Summarise the Confluence page on our deployment process.",
        "The deployment process page documents a three-stage pipeline: staging, canary, and "
        "full production. Staging deploys happen automatically on every merge to main. Canary "
        "releases expose the new version to 5% of traffic for 30 minutes; automated health "
        "checks gate the rollout. Full production promotion requires a manual approval in the "
        "deployment dashboard — any engineer with deploy access can approve. Rollbacks are "
        "one-click from the same dashboard and complete within 90 seconds. The page also "
        "documents four common failure scenarios with runbook links: database migration failure, "
        "health check timeout, canary error spike, and CDN cache invalidation issue. Last "
        "updated three weeks ago by the platform team after the Tuesday incident post-mortem.",
    ),
    (
        "Are there any unread Slack messages I should know about? Actually, just check my email.",
        "I don't have access to Slack, but I checked your email. You have 14 unread messages. "
        "The most important ones: your CTO sent a company-wide note about the Q3 planning "
        "timeline — responses to the team goal survey are due by end of week. The DevOps team "
        "sent an alert that the staging environment will be offline for maintenance Thursday "
        "08:00–10:00 UTC. A recruiter from a partner company forwarded two CVs for the senior "
        "backend engineer role you're hiring for. There's also a thread with three replies from "
        "the design team asking for feedback on the new dashboard mockups — they want input by "
        "tomorrow. The remaining nine emails are newsletters and automated system notifications.",
    ),
    (
        "What's the best way to handle context window overflow in a LangGraph agent?",
        "There are four main strategies for context window pressure in LangGraph. First, "
        "message pruning: keep only the N most recent messages, always preserving the system "
        "prompt and any open tool call/result pairs to avoid malformed message history errors. "
        "Second, summarisation: periodically replace a chunk of older messages with a concise "
        "summary generated by the LLM — this preserves semantic content at lower token cost. "
        "Third, smarter retrieval: instead of injecting all retrieved memory chunks, score them "
        "against a relevance threshold and cap total injected tokens. Fourth, structured "
        "truncation: for tool results that are very long (e.g., a full email thread or large "
        "file), truncate at the tool level before the result enters the message history. "
        "The right combination depends on your use case — agents that need long conversation "
        "fidelity benefit most from summarisation; agents that call many tools benefit most "
        "from tool-result truncation.",
    ),
    (
        "Can you find the last email I sent to the product team about the roadmap?",
        "The most recent email you sent to the product team about the roadmap was sent last "
        "Thursday at 14:32. Subject: 'Re: Q3 Roadmap — Engineering Capacity Constraints'. "
        "You replied to a thread started by the product lead asking for engineering estimates. "
        "Your message listed four items that engineering believes are at risk for Q3: the "
        "recommendation engine rewrite (8 weeks of work remaining, 4 available), the mobile "
        "push notification service (dependency on the notification platform team, slipped twice), "
        "the new admin dashboard (design not finalised), and the data export feature (compliance "
        "review not started). You proposed moving two items to Q4 and asked product to "
        "reprioritise accordingly. The thread has had two replies since then — one from the "
        "product lead and one from the CTO.",
    ),
    (
        "What does the architecture decision record say about our message queue choice?",
        "The ADR for the message queue decision (ADR-014, written six months ago) documents the "
        "evaluation of three options: RabbitMQ, Apache Kafka, and AWS SQS. The team chose Kafka "
        "for the following reasons: message replay capability for the event sourcing pattern "
        "already in use, better throughput at projected peak load (estimated 50k messages/sec), "
        "and existing team familiarity from a previous project. Trade-offs accepted: higher "
        "operational complexity compared to SQS, and a requirement to run Zookeeper (since "
        "updated to KRaft mode which removes this dependency). SQS was ruled out due to the "
        "10-year message retention limit and lack of replay. RabbitMQ was ruled out due to "
        "performance at scale. The ADR was approved by the CTO and the platform lead.",
    ),
    (
        "Show me recent web search results about LangGraph multi-agent patterns.",
        "I ran a web search for 'LangGraph multi-agent patterns' and found several relevant "
        "resources. The LangGraph documentation has a section on multi-agent architectures "
        "covering three patterns: supervisor (one agent coordinates sub-agents), hierarchical "
        "(nested supervisor trees), and network (agents communicate peer-to-peer via message "
        "passing). A recent blog post from a large tech company describes their production "
        "implementation of a supervisor pattern for a customer support system — they found that "
        "explicit hand-off messages with structured context summaries outperformed passing the "
        "raw full conversation history. A GitHub repository has example code for a "
        "parallelisation pattern where independent sub-agents run concurrently and their results "
        "are merged. Academic papers from 2024 are starting to benchmark multi-agent LangGraph "
        "systems on complex reasoning tasks. Do you want links to any of these?",
    ),
    (
        "Remind me what we decided about database migrations in our team agreement.",
        "Your team agreement document (last updated two months ago) has a dedicated section on "
        "database migrations. Key decisions: all migrations must be backwards-compatible with "
        "the previous deployed version to support zero-downtime deploys — this means no "
        "immediate column drops or type changes without a two-phase migration. Migrations are "
        "reviewed in the same PR as the application code that requires them. The team uses "
        "Alembic for Python services and Flyway for the legacy Java services. A dry-run on "
        "staging is mandatory before any migration that modifies a table with more than one "
        "million rows. Post-migration, the on-call engineer monitors error rates for 30 minutes. "
        "The team learned this policy the hard way after a migration in January caused a 12-minute "
        "outage due to a table lock.",
    ),
    (
        "What are the key metrics I should review before the monthly engineering review?",
        "For the monthly engineering review, the key metrics are split across four categories. "
        "Reliability: P99 API latency (target <200ms), error rate (target <0.1%), and uptime "
        "(target 99.9%). Velocity: story points delivered vs. committed, number of deployments "
        "per week, and lead time from commit to production. Quality: test coverage percentage, "
        "number of open critical bugs, and post-incident review completion rate. Cost: compute "
        "spend vs. budget, cost per API request trend, and any anomalous resource usage. "
        "You'll also want to pull the Langfuse dashboard for AI feature token usage and cost "
        "if the AI features are in scope for this review. The last review deck is in Confluence "
        "under Engineering > Reviews if you want to use it as a template.",
    ),
    (
        "Is there anything urgent in my inbox that needs a response today?",
        "Three emails in your inbox appear to need a response today. First, the hiring manager "
        "from the design team sent a note at 08:12 asking if you can join a candidate debrief "
        "call at 15:00 today — they need a technical perspective. Second, a customer success "
        "manager escalated a client question about the data export API rate limits at 09:47; "
        "the client is on an enterprise plan and expects a response within the same business day "
        "per SLA. Third, your skip-level sent a calendar invite for a 30-minute informal chat "
        "next Tuesday and asked if the time works — a quick reply confirming or proposing an "
        "alternative would be courteous. Everything else can wait until tomorrow.",
    ),
    (
        "Can you search the web for best practices on LLM prompt versioning?",
        "I searched for 'LLM prompt versioning best practices' and found a few strong patterns. "
        "The most commonly cited approach is treating prompts like code: store them in version "
        "control alongside the application, use semantic versioning (major for breaking behaviour "
        "changes, minor for improvements, patch for typo fixes), and link each prompt version to "
        "the eval results that justified it. Observability platforms like Langfuse and LangSmith "
        "support tagging LLM calls with a prompt version so you can compare performance across "
        "versions in production traces. A second approach is a dedicated prompt registry (a "
        "database or config service) that the application fetches at runtime — this enables "
        "A/B testing without code deploys. The risk is prompt-code coupling: if the prompt "
        "format changes but the parsing code doesn't, you get silent failures. A third pattern "
        "is prompt unit tests: a suite of input/expected-output pairs that runs on every prompt "
        "change, similar to snapshot tests in UI development.",
    ),
    (
        "What files did I most recently modify in the agent project?",
        "The most recently modified files in the agent project, based on the directory listing, "
        "are: src/agent/graph.py (modified today, likely the context budget changes), "
        "src/agent/memory/budget.py (today), src/agent/config.py (today), "
        "src/agent/memory/semantic.py (yesterday), src/agent/memory/episodic.py (two days ago), "
        "src/agent/tools/__init__.py (three days ago), and tests/memory/test_episodic.py "
        "(three days ago). The most active area of development is clearly the memory layer — "
        "five of the seven recently modified files are in the memory module. The graph.py "
        "changes today are the context budget node insertion.",
    ),
    (
        "Summarise the meeting notes from yesterday's architecture review.",
        "I found the meeting notes for yesterday's architecture review in your email. "
        "Attendees: six engineers plus the CTO. Agenda item 1 — ClickHouse migration: the team "
        "agreed to proceed with a hybrid model where OLTP queries remain on Postgres and analytics "
        "queries route to ClickHouse. Partitioning strategy to be decided by the data team by "
        "Friday. Agenda item 2 — API gateway: the proposal to add a dedicated API gateway layer "
        "was deferred; the current nginx setup is sufficient for 12 months at projected traffic. "
        "Agenda item 3 — Secret management: unanimous agreement to migrate from environment "
        "variables to HashiCorp Vault. Spike ticket created (DF2LPE-538). Action items: three "
        "tickets were filed. Next architecture review is in two weeks.",
    ),
    (
        "What is my Langfuse dashboard showing for token usage this week?",
        "I don't have direct access to your Langfuse dashboard, but based on the episodic memory "
        "logs from this week's agent runs, here's an estimate: the agent has run 23 times this "
        "week. Average token usage per run is approximately 2,400 tokens (prompt: 1,800, "
        "completion: 600). Total estimated tokens this week: ~55,200. At Gemini 2.0 Flash "
        "pricing ($0.075 per million input tokens, $0.30 per million output tokens), the "
        "estimated cost for agent usage this week is roughly $0.004 — well within budget. "
        "The highest-token run was a meeting prep query that pulled calendar + email + Confluence "
        "data simultaneously (8,200 tokens total). For accurate figures, check the Langfuse "
        "dashboard directly — it aggregates by trace and breaks down by model.",
    ),
    (
        "What's the status of the mobile push notification service that was blocked?",
        "Based on the last update in JIRA (DF2LPE-489, last updated five days ago by Carlos), "
        "the mobile push notification service is still blocked on the notification platform team. "
        "The blocker is that the platform team's new event routing API is not yet stable — "
        "they released v2-beta last week but it has a known bug with batch sends over 1,000 "
        "events. The platform team's target for a stable release is end of next week. "
        "Carlos added a comment yesterday saying he'll unblock the mobile work as soon as "
        "the platform team cuts a release candidate. The ticket is 6 weeks old and has been "
        "escalated once already. If the platform team slips again, this will miss Q3. "
        "You may want to raise it in the Monday planning meeting.",
    ),
    (
        "Help me write a query to find all emails where I was CC'd but didn't reply.",
        "To find emails where you were CC'd but didn't reply, you can use Gmail's search syntax. "
        "In the search bar try: `cc:me -from:me` — this finds all emails where your address "
        "appears in the CC field and filters out threads where you've sent a reply. To narrow "
        "it to the last 30 days, add `newer_than:30d`. If you want only unread ones, add "
        "`is:unread`. The full query: `cc:me -from:me newer_than:30d`. Note that this won't "
        "catch threads where you replied and your reply was the last message, but where the "
        "conversation is still active — for those you'd need to cross-reference with threads "
        "that have activity after your last message. Do you want me to run this search via "
        "the Gmail tool and show you the results?",
    ),
    (
        "What are the upcoming public holidays that might affect our sprint planning?",
        "Looking at the next eight weeks, there are two public holidays that could affect "
        "sprint capacity depending on your team's locations. In three weeks: a bank holiday "
        "in the UK (Bank Holiday Monday) — if any team members are UK-based, that's one day "
        "of reduced capacity. In six weeks: a federal holiday in the US (Labor Day) — US-based "
        "team members will likely be off. If you're running two-week sprints, the bank holiday "
        "falls mid-sprint and Labor Day falls at the start of a sprint, which is a good time to "
        "reduce commitment. I'd recommend flagging both in your next sprint planning session and "
        "adjusting story point targets by roughly 10-15% for the affected sprints.",
    ),
    (
        "Can you look up any documentation on our current feature flag system?",
        "I found two relevant Confluence pages and one Slack thread (via email summary) about "
        "the feature flag system. The main documentation page describes LaunchDarkly as the "
        "current provider, with flags organised into three namespaces: release flags (for "
        "controlled rollouts), kill switches (for emergency disabling of features), and "
        "experiment flags (for A/B tests). The rollout process page documents that any flag "
        "affecting payment or auth flows requires a security review before enabling. The Slack "
        "thread (from the Tuesday incident email summary) flags a gap in the current process: "
        "there's no mandatory load-test requirement before enabling flags that change retry "
        "behaviour — this has been added to the process checklist as an action item. "
        "A new Confluence page for the updated process is being drafted by the platform team.",
    ),
    (
        "What was the outcome of the compliance audit last quarter?",
        "The Q2 compliance audit summary was sent by the legal team six weeks ago. The overall "
        "result was a pass with three minor findings. Finding 1: personal data fields in the "
        "analytics pipeline were not being masked before ingestion into the data warehouse — "
        "remediation was a data transformation step added to the pipeline (closed). Finding 2: "
        "audit log retention was set to 60 days, below the 90-day requirement for PCI DSS — "
        "corrected by updating the log retention policy (closed). Finding 3: two service "
        "accounts had excessive IAM permissions granted during a previous incident and not "
        "revoked — the principle of least privilege was re-applied (closed). All three findings "
        "were remediated before the quarter closed. The next audit is scheduled for Q4.",
    ),
    (
        "Is there a way to reduce the startup time for our test suite?",
        "There are several approaches to reduce test suite startup time. First, parallelisation: "
        "pytest-xdist can run test files in parallel across CPU cores — for a suite like yours "
        "with 50+ tests, this can cut wall-clock time by 40-60%. Second, test isolation: if "
        "you're spinning up real database connections or external service clients in every test, "
        "move those to session-scoped fixtures so they're created once. Third, import cost: "
        "the agent imports heavy dependencies (LangChain, Chroma, Google Auth) at module import "
        "time — lazy imports or conditional imports can help. Fourth, fixture caching: the "
        "Chroma and SQLite memory instances could be shared across tests in a tmp_path session "
        "fixture. Looking at your current test files, the biggest win is probably pytest-xdist "
        "plus session-scoped memory fixtures — that could reduce your test time from minutes "
        "to under 30 seconds.",
    ),
    (
        "What tasks did I complete yesterday according to my calendar and JIRA?",
        "Based on your calendar and JIRA data for yesterday: from the calendar, you had a "
        "2-hour deep work block in the morning (9–11 AM, no meetings) and two meetings in the "
        "afternoon. From JIRA, three tickets were moved to Done yesterday: DF2LPE-522 (add "
        "connection pool configuration to the service settings), DF2LPE-526 (fix flaky test "
        "in the authentication module), and DF2LPE-529 (update the API rate limit headers to "
        "follow RFC 6585). Two comments were added by you on open tickets, suggesting active "
        "review work. No emails were sent after 16:00, which usually indicates an early wrap. "
        "It looks like a productive day — three tickets shipped and no incidents.",
    ),
    (
        "Can you help me prepare for my 1-on-1 with my manager tomorrow?",
        "For your manager 1-on-1 tomorrow, here's what I'd suggest bringing based on recent "
        "activity. Accomplishments since the last 1-on-1: shipped DF2LPE-502 (rate limiting "
        "middleware), closed three compliance audit findings, led the Tuesday incident "
        "post-mortem and filed all follow-up tickets. Current blockers you might want to raise: "
        "the mobile push notification service is stuck on a platform team dependency (6 weeks "
        "old, may miss Q3), and DF2LPE-498 is blocked on DevOps infrastructure access. "
        "Development: if you want to discuss career progression, the context budget work "
        "you're doing now is good material — it's a concrete example of production-readiness "
        "thinking. Questions to ask: Q3 planning timeline and whether the team's capacity "
        "constraints have been communicated to product.",
    ),
    (
        "What's our current test coverage percentage and how does it compare to last month?",
        "I can't directly query your CI coverage reports, but based on the last two coverage "
        "report emails in your inbox (one from this week, one from four weeks ago): current "
        "test coverage is 71% (up from 64% last month). The biggest gains were in the memory "
        "module (new tests added for episodic and semantic memory) and the tools module "
        "(additional edge case tests). The main coverage gaps remain in the graph module "
        "(51% coverage — the HITL interrupt paths are hard to unit test) and the auth module "
        "(43% coverage — OAuth flows require real credentials). Your team's target is 80% "
        "overall by Q3 close. At the current rate of improvement (~7 points/month), you're "
        "on track if the graph and auth modules get some test attention this sprint.",
    ),
    (
        "Find any emails about the Q3 offsite and summarise what's been decided.",
        "I found five emails about the Q3 offsite over the past three weeks. Decisions made: "
        "the offsite is confirmed for the third week of September, two days, in-person at the "
        "company's Berlin office. Agenda is being set by the CTO — draft agenda expected by "
        "end of this week. Travel and accommodation are being booked centrally by operations; "
        "you should have received a form to confirm attendance (it's in your inbox, unanswered). "
        "Budget is €500 per person for travel. Sessions confirmed so far: company strategy "
        "presentation, team roadmap alignment, and a social dinner on the first evening. "
        "Sessions still being proposed: a technical deep-dive session and a process retrospective. "
        "Action needed: fill in the attendance form by Friday.",
    ),
    (
        "How is the personal agent project going overall? Give me an honest assessment.",
        "Based on the git history, JIRA tickets, and the master plan document, here's an honest "
        "assessment. What's going well: you've shipped a solid foundation — working ReAct loop "
        "with LangGraph, Langfuse tracing integrated, all the core data source connectors "
        "(Gmail, Calendar, filesystem, web search), human-in-the-loop for write operations, "
        "retry and fallback logic, and now a complete memory layer (episodic + semantic). "
        "The code is clean and well-tested for a side project. What could be better: the "
        "system prompt is still a placeholder — it hasn't been versioned or iteratively "
        "improved (Phase 4). There are no evals yet (Phase 7). The context budget work you're "
        "doing now is the right next step. Honest risk: the project has breadth (many integrations) "
        "but still lacks depth in any one area. For an interview portfolio, pick one or two "
        "impressive end-to-end demos and make them bulletproof rather than continuing to add "
        "features. The meeting-prep workflow is your strongest candidate.",
    ),
]

_EMAIL_DATA = [
    ("Q3 Planning Kickoff — Action Required", "sarah.chen@company.com", "2026-04-14",
     "Hi team, as we head into Q3 planning I want to make sure everyone has completed "
     "the capacity survey before our planning session on Thursday. The survey asks you to "
     "estimate available focus hours accounting for vacation, on-call rotations, and "
     "cross-team commitments. This year we're also asking for a rough breakdown between "
     "maintenance work and new feature work, as product has asked us to be more explicit "
     "about the split. If you have dependencies on other teams that could affect your "
     "estimates, please flag them in the notes field. The planning doc is linked in the "
     "survey — please read section 3 on engineering priorities before filling it in. "
     "Deadline is Wednesday EOD. If you have questions, ping me in the planning channel."),
    ("Re: Data Pipeline Migration — Staging Results", "priya.mehta@company.com", "2026-04-14",
     "Following up on the staging run from yesterday: the transformation layer processed "
     "the full day's worth of events in 4 minutes 22 seconds end-to-end, which is under "
     "our 5-minute SLO target. Memory usage peaked at 2.1 GB, well within the 4 GB "
     "container limit. One issue to flag: three currency normalisation events were dropped "
     "when the exchange rate API returned a 429 during the rate-limited test window. I've "
     "added a dead-letter queue for those and they retry automatically. The retry logic "
     "worked correctly in the subsequent test run — all three events were reprocessed. "
     "I'll send the full test report to the architecture review Confluence page by tomorrow. "
     "Plan is to run the migration on the real data set this weekend. I'll be on-call."),
    ("Security Review Required — Feature Flag Change", "security@company.com", "2026-04-13",
     "Automated notification: a feature flag affecting the authentication flow "
     "(flag ID: auth-v2-token-storage) has been submitted for production enablement. "
     "Per the feature flag process policy updated after the Tuesday incident, all flags "
     "affecting authentication or payment flows require a security review before they are "
     "enabled in production. The review checklist is attached to this email. Required "
     "reviewers: security team lead and the engineering manager for the auth service. "
     "Please complete the review within 48 hours or the flag will be automatically "
     "blocked from production enablement. The submitting engineer has been notified. "
     "If you have questions about the review process, contact the security team directly."),
    ("Interview Debrief Request — Senior Backend Engineer", "hiring@company.com", "2026-04-13",
     "We have completed onsite interviews for two candidates for the senior backend "
     "engineer role. Candidate A (referred internally, 8 years experience, strong on "
     "distributed systems, weaker on frontend) scored an average of 3.8/5 across "
     "interviewers. Candidate B (external application, 6 years experience, very strong "
     "on databases and query optimisation) scored 4.1/5. Hiring manager is leaning "
     "toward Candidate B but wants a second opinion on the system design round before "
     "extending an offer. Can you join a 30-minute debrief call today at 15:00 to discuss? "
     "I'll share the interview feedback documents before the call. If today doesn't work, "
     "please suggest an alternative — we'd like to move quickly on this role."),
    ("JIRA Sprint 34 — Daily Digest", "jira@company.atlassian.net", "2026-04-14",
     "Sprint 34 digest for 14 April. Tickets moved to Done: DF2LPE-522 (add connection "
     "pool config), DF2LPE-526 (fix flaky auth test), DF2LPE-529 (RFC 6585 rate limit "
     "headers). Tickets moved to In Progress: DF2LPE-537 (investigate slow user prefs "
     "query), DF2LPE-502 (rate limiting middleware). Tickets newly blocked: none. "
     "Comments added: 14 across 9 tickets. Sprint burndown is on track — 31 of 80 points "
     "completed with 5 days remaining. No tickets are approaching their due date without "
     "progress. Three tickets have been sitting In Progress for more than 4 days without "
     "a status update: DF2LPE-498, DF2LPE-517, DF2LPE-531. Action: please update or "
     "add a comment if these are still active."),
    ("Legal: Open Source Licence Audit Due Friday", "legal@company.com", "2026-04-12",
     "Reminder that the annual open source licence audit is due this Friday. Engineering "
     "teams are required to submit a manifest of all open-source dependencies used in "
     "production services, along with their licences. The automated scan has already "
     "generated a preliminary manifest — please review it for accuracy and flag any "
     "discrepancies. Key areas to check: any dependencies added in the last six months "
     "that have not been through the licence review process, any GPL-licensed code that "
     "might create a copyleft obligation, and any packages that have changed licence since "
     "the last audit. The review form and this year's checklist are attached. If you find "
     "any GPL or SSPL-licensed dependencies, escalate to the legal team immediately."),
    ("Incident Post-Mortem Draft — Tuesday Outage", "alex.rodriguez@company.com", "2026-04-11",
     "I've written up the post-mortem draft for the Tuesday payment service outage. "
     "Summary: the feature flag enabling the new retry policy caused a retry storm that "
     "saturated the database connection pool. Timeline, root cause, and contributing "
     "factors are all documented. I have three proposed corrective actions: (1) mandatory "
     "load test for any flag that changes retry behaviour, (2) connection pool monitoring "
     "alert at 80% utilisation, (3) update the feature flag checklist. Please review the "
     "draft before Thursday's post-mortem meeting — I've shared it in Confluence. "
     "If you want to add contributing factors or correct anything in the timeline, add a "
     "comment directly in the document. I'll incorporate feedback before the meeting."),
    ("Re: ClickHouse Provisioning Update", "devops@company.com", "2026-04-14",
     "Update on the ClickHouse cluster provisioning. The initial capacity estimate "
     "was revised upward after the staging performance tests showed higher memory usage "
     "than expected. We're now provisioning 3 nodes (was 2) with 16 vCPUs and 64 GB RAM "
     "each. This adds approximately $800/month to the infrastructure cost but gives us "
     "comfortable headroom for the projected load. The cluster will be ready Thursday "
     "morning — I'll send the connection string and credentials to the data team via the "
     "secrets manager. The Terraform config for the cluster is being reviewed by two "
     "engineers. Once approved, the apply will take about 20 minutes. I'll ping the "
     "channel when it's live."),
    ("Customer Escalation — API Rate Limits (Enterprise)", "customer-success@company.com", "2026-04-14",
     "Enterprise customer Acme Corp has escalated a question about the data export API "
     "rate limits. Their use case: nightly batch export of 2 years of transaction data "
     "for their internal analytics platform. The current rate limit is 1,000 requests "
     "per minute, and their export job is hitting the limit and failing partway through. "
     "They're asking either for a higher rate limit or a bulk export endpoint. Per our "
     "enterprise SLA, we need to respond within the same business day. I've checked and "
     "a bulk export endpoint is on the roadmap for Q4. Short-term options: temporary "
     "rate limit increase (requires engineering approval), or a workaround guide for "
     "chunking the export across multiple nights. Can you advise on the best response?"),
    ("Vault Migration Spike — Kickoff", "marcus.okonkwo@company.com", "2026-04-14",
     "Following the architecture review decision to migrate to HashiCorp Vault, I've "
     "started the spike (DF2LPE-538). Initial findings: we currently have 47 secrets "
     "spread across environment variables in Kubernetes and a legacy .env file system "
     "in the older services. The migration path is: stand up a Vault instance in our "
     "AWS account, migrate secrets service by service, update deployment configs, and "
     "remove the old env var approach. Vault Kubernetes auth is the right integration "
     "method here — services authenticate via their service account without needing a "
     "static Vault token. Estimated effort: 3 sprints for full migration. I'll have "
     "a detailed plan by end of week. One risk: the legacy Java services have secrets "
     "baked into JVM startup flags — those will need extra work."),
    ("Design Review: New Dashboard Mockups", "design-team@company.com", "2026-04-13",
     "We've finalised the v2 mockups for the new analytics dashboard and would love "
     "your technical feedback before we move to the handoff phase. The main changes "
     "from v1: a new real-time metrics panel that auto-refreshes every 30 seconds, "
     "a redesigned filter sidebar that supports multi-select with logical operators, "
     "and a new export button that triggers our data export API. We need to know: "
     "is the 30-second auto-refresh technically feasible without impacting backend "
     "load? Are there any concerns about the filter query complexity with multi-select "
     "logical operators? The export button — should we warn users about rate limits "
     "in the UI, or handle it gracefully in the background? Feedback requested by "
     "tomorrow EOD so we can hit the handoff deadline."),
    ("Weekly Infra Cost Report", "finops@company.com", "2026-04-14",
     "Weekly infrastructure cost summary for the week ending 13 April. Total spend: "
     "$12,340 (budget: $13,000, 95% utilised). Breakdown: compute $7,200 (up 8% week "
     "on week — new staging environment stood up for pipeline testing), storage $2,100 "
     "(flat), database $1,800 (up 12% — ClickHouse staging cluster), networking $800 "
     "(flat), AI/ML APIs $440 (Gemini API calls up 23% — agent testing in progress). "
     "Three cost anomalies flagged for review: the staging ClickHouse cluster is running "
     "24/7 but only used during business hours — consider scheduling a shutdown from "
     "20:00 to 07:00. A developer workstation has had GPU instances running for 5 days "
     "— please confirm this is intentional. Lambda invocation count is unusually high "
     "on the event router — may be related to the Tuesday incident retry storm."),
    ("Re: Q3 Offsite — Attendance Confirmation Needed", "operations@company.com", "2026-04-10",
     "This is a reminder that we need your attendance confirmation for the Q3 engineering "
     "offsite by Friday 17 April. The offsite is scheduled for 23–24 September in Berlin. "
     "We're booking flights and accommodation centrally to get better rates, so we need "
     "confirmations before we can book. The form asks for dietary requirements, any "
     "accessibility needs, whether you prefer to arrive the evening before for the early "
     "morning start, and your preferred flight departure airport. Budget is €500 for "
     "travel and the company covers accommodation. If you can't attend in person, there "
     "will be a video link for the strategy presentation but the rest of the sessions are "
     "in-person only. Please fill in the form linked below and submit it before Friday."),
    ("Grafana Alert: Staging DB CPU > 80%", "grafana-alerts@company.com", "2026-04-14",
     "Alert triggered: staging Postgres instance CPU utilisation exceeded 80% threshold "
     "at 14:23 UTC. This is an informational alert for the staging environment — no "
     "immediate action required unless this is blocking active development. Current "
     "utilisation: 84%. The alert typically fires during integration test runs that "
     "involve large-volume data loads. If this is unexpected, check for any runaway "
     "queries in pg_stat_activity. The alert will auto-resolve once CPU drops below 70%. "
     "Recent context: the data pipeline staging tests were running at the time of this "
     "alert, which likely explains the elevated CPU. Runbook link is in the Grafana panel "
     "if manual investigation is needed. This alert fires on average twice per week."),
    ("Monthly 1-on-1 Prep — Skip Level with CTO", "cto@company.com", "2026-04-09",
     "Looking forward to our skip-level chat next Tuesday. I like to keep these informal "
     "but it helps if you come with a few things in mind: what's one thing the company "
     "could do better to support your work? Is there anything you wish leadership knew "
     "about that isn't visible from the top? What's one technical decision you've made "
     "recently that you're proud of, and why? And what's one thing that's been bugging "
     "you — something inefficient, frustrating, or just not working well? No need to "
     "prepare slides or a formal update. I'll share context on where the company is "
     "heading strategically, and we can talk through how that maps to what you're "
     "working on. See you Tuesday at 15:00."),
    ("Re: API Documentation Update — v2 Endpoints", "tech-writing@company.com", "2026-04-11",
     "I've reviewed the draft API documentation you submitted for the v2 endpoints "
     "and have a few questions before I finalise the public docs. First, the rate limit "
     "table shows 1,000 requests/minute for all endpoints — is this correct for the "
     "bulk export endpoint as well, or does it have a separate limit? Second, the "
     "authentication section references an API key header but the code examples use "
     "Bearer tokens — which is correct for v2? Third, the error response schema shows "
     "a 'details' field but I couldn't find that in the actual API responses I tested "
     "against staging. Finally, are there any endpoints in v2 that are only available "
     "to enterprise customers? If so, we'll need to add a tier indicator. Please "
     "reply with clarifications so I can ship the docs this week."),
    ("PR Review Request: Rate Limiting Middleware", "alex.rodriguez@company.com", "2026-04-14",
     "Could you review DF2LPE-502? It's the rate limiting middleware implementation. "
     "The PR adds a configurable sliding window rate limiter at the API gateway layer, "
     "using Redis for the counter storage. Key decisions I made that I'd like your "
     "input on: used a Lua script for the atomic counter increment and expiry — this "
     "avoids race conditions but ties us to Redis. Used a 429 response with "
     "Retry-After header (per RFC 6585). Configured default limits in environment "
     "variables rather than hardcoding. The PR has 18 commits (been iterating on "
     "the Redis key structure) but the final implementation is clean. Tests cover the "
     "happy path, rate exceeded path, and Redis unavailability fallback (passes through "
     "without limiting if Redis is down — intentional, fail-open for reliability)."),
    ("Compliance Audit Q2 — Final Report", "legal@company.com", "2026-04-01",
     "The Q2 compliance audit has been completed and all three findings have been "
     "remediated and verified. Finding 1 (personal data masking in analytics pipeline) — "
     "verified closed. The data transformation step is now in production and running "
     "correctly. Finding 2 (audit log retention below PCI DSS requirement) — verified "
     "closed. Log retention is now set to 90 days in all production systems. Finding 3 "
     "(excessive IAM permissions on service accounts) — verified closed. Principle of "
     "least privilege has been applied and the access review is now on a quarterly "
     "schedule. The final report has been submitted to the auditors. The next audit is "
     "scheduled for Q4. Well done to the engineering team for remediating all findings "
     "before the quarter close — this is the first time we've achieved a clean close "
     "in three quarters."),
    ("Platform Team: Notification API v2 Release Candidate", "platform@company.com", "2026-04-13",
     "Good news: the notification platform API v2 release candidate is available in "
     "staging. The batch send bug that was blocking the mobile push notification service "
     "has been fixed — we've tested with batches of up to 50,000 events without issues. "
     "The release candidate will be promoted to production on Wednesday pending sign-off "
     "from the two consuming teams (mobile and web push). For the mobile team: the batch "
     "endpoint signature has changed slightly — the 'events' field is now 'notifications' "
     "and the delivery_time field accepts ISO 8601 format. Updated API docs are in "
     "Confluence. Carlos, please test against the staging release candidate before "
     "Wednesday and confirm you're unblocked. We'll cut the stable release Wednesday "
     "afternoon if both teams sign off."),
    ("Q3 Goal Survey — Deadline Reminder", "cto@company.com", "2026-04-14",
     "This is a reminder that the Q3 goal survey closes at 18:00 today. As of this "
     "morning, 14 of 22 engineers have submitted responses. The survey is short — "
     "about 10 minutes. It asks you to rate how well last quarter's engineering goals "
     "aligned with your day-to-day work, what the biggest technical challenges are for "
     "the next quarter, and what support from leadership would make the most difference. "
     "Your input directly influences the Q3 planning session on Thursday. If you've "
     "already submitted, thank you. If you haven't, please do so before 18:00. "
     "I read every response personally and will share anonymised themes at the all-hands "
     "next week. The survey link was sent on Monday — check your inbox if you can't find "
     "it, or reply to this email and I'll resend it."),
    ("Re: Slow Query Investigation — User Preferences Table", "dba@company.com", "2026-04-12",
     "I've investigated the slow query on the user preferences table (DF2LPE-537). "
     "Root cause: the query that fetches all active A/B test assignments for a user "
     "does a full table scan because the composite index (user_id, experiment_id, status) "
     "is being ignored due to a function call on the status column in the WHERE clause "
     "(`LOWER(status) = 'active'`). Fix: either remove the LOWER() call (status values "
     "are already stored in lowercase) or add a functional index on LOWER(status). "
     "I recommend removing the LOWER() call — it's defensive code that doesn't add "
     "value. Query time drops from 340ms to 2ms with this change. I've opened a PR "
     "with the fix. Note: there are three other queries in the same file with the same "
     "pattern — I've fixed all of them in the same PR since the change is trivial."),
    ("Weekly Team Sync — Notes and Action Items", "team-lead@company.com", "2026-04-13",
     "Notes from today's weekly team sync. Attendees: all 8 team members. Highlights: "
     "sprint 34 is on track, three tickets shipped yesterday. Carlos confirmed he'll be "
     "unblocked on the mobile push service once the platform team releases the v2 API "
     "Wednesday. The ClickHouse cluster is being provisioned Thursday. Post-mortem for "
     "Tuesday's outage is Thursday 14:00. Action items: (1) Everyone complete Q3 goal "
     "survey by today 18:00. (2) All blocked tickets to have a comment by tomorrow "
     "explaining the block. (3) Engineers with tickets In Progress >4 days to update "
     "JIRA. (4) Anyone with pending attendance form for Berlin offsite to submit by "
     "Friday. Next sync is Monday — come prepared with what you plan to ship next week."),
    ("Automated Test Report — Build #1,247", "ci@company.com", "2026-04-14",
     "Build #1,247 completed on branch feature/context-budget. Results: 47 tests passed, "
     "0 failed, 2 skipped. Test execution time: 38 seconds. Coverage: 71.4% (up from "
     "70.9% on the previous build). New tests added in this build: 6 tests in "
     "tests/memory/test_context_pressure.py. Coverage changes: agent/memory/budget.py "
     "increased from 62% to 89% (new TokenCounter class is well-covered). "
     "agent/graph.py decreased slightly from 58% to 55% (the new check_context_budget "
     "node is not yet tested via integration test). Linting: no issues found. "
     "Security scan: no high or critical vulnerabilities detected. Build artifacts "
     "are available for 7 days. Branch is 3 commits ahead of main."),
    ("Re: Recommendation Engine Rewrite — Capacity Risk", "product@company.com", "2026-04-10",
     "Thanks for the candid assessment of engineering capacity in your email last week. "
     "I've discussed with the CTO and we agree that the recommendation engine rewrite "
     "should move to Q4. The new Q3 priorities for engineering (from product's perspective) "
     "are: (1) complete the data pipeline migration — this unblocks the analytics team "
     "and is a dependency for two other Q3 product initiatives. (2) Ship the bulk export "
     "API — enterprise customers are asking for it and it's a churn risk. (3) Complete "
     "the compliance remediation work. The admin dashboard can also slip to Q4 if needed. "
     "I'll update the roadmap and communicate the changes to stakeholders. Can you confirm "
     "with your team that the revised Q3 scope is achievable? I'd like to lock this down "
     "before Thursday's planning session."),
    ("HashiCorp Vault — Pricing and Licensing", "procurement@company.com", "2026-04-11",
     "Following the architecture decision to adopt HashiCorp Vault for secrets management, "
     "I've got the pricing information you requested. Vault Community Edition is open "
     "source and free but lacks enterprise features (namespaces, HSM support, "
     "performance replication). Vault Enterprise starts at approximately $12,000/year "
     "for a small deployment. HCP Vault (managed cloud version) is $0.08 per secret "
     "per month plus compute, which would be approximately $3,000–5,000/year based on "
     "your estimated 47 secrets and usage patterns. Recommendation from procurement: "
     "start with Community Edition for the migration and evaluate whether you need "
     "enterprise features after 6 months of use. The main enterprise features you might "
     "need are namespaces (for multi-team isolation) and audit logging at scale. "
     "Let me know how you'd like to proceed and I'll get the contract started."),
]

_MEMORY_CHUNKS = [
    (0.95, "documents",
     "The team uses a hybrid Postgres/ClickHouse setup for database workloads. Postgres handles "
     "all OLTP operations including user authentication, session management, payment processing, "
     "and transactional writes. ClickHouse is used exclusively for analytics queries — event "
     "aggregations, funnel analysis, and the business intelligence dashboards. The decision to "
     "adopt this hybrid model was made in the Q2 architecture review after benchmarking showed "
     "that complex GROUP BY queries on the events table were causing read contention on the "
     "Postgres primary. ClickHouse reduces analytical query latency by 95% at the cost of "
     "additional operational complexity. Data flows from Postgres to ClickHouse via the Kafka "
     "event stream, with a replication lag of approximately 30 seconds. The data pipeline team "
     "owns the Kafka consumers and the ClickHouse schema. Engineers writing analytics queries "
     "should use the ClickHouse read replica connection string from Vault."),
    (0.91, "interactions",
     "User asked: How do I set up a new Google Calendar OAuth credential for the agent? "
     "Agent answered: To set up Google Calendar OAuth, download the credentials JSON from "
     "the Google Cloud Console (APIs & Services > Credentials > OAuth 2.0 Client IDs). "
     "Place the file at credentials/google_credentials.json in the project root. On first "
     "run, the auth module opens a browser window for the OAuth consent flow — complete it "
     "and the token is saved to credentials/token.json. Subsequent runs refresh the token "
     "automatically. Scopes required: calendar.readonly for read-only access. If you need "
     "write access (creating events), add calendar.events to the scopes list in "
     "src/agent/auth/google.py. Both credentials/ paths are gitignored to prevent "
     "accidentally committing secrets to the repository."),
    (0.88, "documents",
     "The LangGraph agent uses a human-in-the-loop (HITL) pattern to gate write operations. "
     "When the LLM decides to call a tool that modifies external state (creating a draft email, "
     "sending email, creating calendar events, deleting files), the graph pauses execution at "
     "the human_review_node and emits an interrupt payload. The CLI displays the proposed "
     "action and waits for the user to type 'approve' or 'reject'. If approved, the graph "
     "resumes and executes the tool. If rejected, a ToolMessage is injected with a rejection "
     "notice so the LLM can acknowledge the cancellation gracefully. The interrupt mechanism "
     "uses LangGraph's interrupt() function combined with SqliteSaver for checkpointing — "
     "the graph state is persisted to disk so the run can resume even after a process restart. "
     "Thread IDs are per CLI invocation (UUID) to keep runs independent."),
    (0.85, "interactions",
     "User asked: Why is the agent retrying a failed Gmail API call? Agent answered: The "
     "RetryPolicy in graph.py retries tool calls that fail with transient errors. The policy "
     "retries on ConnectionError, TimeoutError, and HttpError with status 429 or 5xx. It does "
     "NOT retry on 4xx errors (except 429) because those represent permanent failures — wrong "
     "credentials, resource not found, or invalid arguments — where retrying won't help. The "
     "backoff sequence is 1 second, then 2 seconds (exponential with jitter), for a maximum "
     "of 3 attempts total. If all attempts fail, the tools_with_fallback wrapper catches the "
     "exception and injects an error ToolMessage so the graph continues rather than crashing. "
     "The LLM sees the error on the next reasoning step and can inform the user gracefully."),
    (0.82, "documents",
     "Episodic memory (SQLite, at data/episodic.db) records every agent run with the following "
     "fields: run ID (UUID), timestamp (UTC ISO 8601), user input, final output, list of tools "
     "called, token usage breakdown (prompt/completion/total), estimated cost in USD, success "
     "flag, and error message if failed. The EpisodicMemory class provides three query methods: "
     "log_run() for inserting a new record, get_recent_runs(n) for retrieving the N most recent "
     "runs in reverse chronological order, and search_runs(query, n) for keyword search over "
     "user input and final output fields. The memory is populated after each agent run in "
     "log_run_to_memory() which is called from cli.py after the graph finishes. Token usage "
     "and cost are extracted from the LLM's usage_metadata on the final AIMessage."),
    (0.79, "interactions",
     "User asked: What's the difference between semantic and episodic memory in this project? "
     "Agent answered: Episodic memory (SQLite) is a structured log of every agent run — it "
     "records what you asked, what the agent answered, which tools were called, and how many "
     "tokens it cost. Think of it as an activity log. You query it by keyword or by recency. "
     "Semantic memory (Chroma + embeddings) stores text in a vector database and retrieves by "
     "similarity. It has two collections: 'documents' for files you explicitly ingest, and "
     "'interactions' for past user/agent conversation pairs. You query it with a question and "
     "get back the most semantically similar chunks above a relevance threshold. The two "
     "memory types are complementary: episodic is for 'what happened when', semantic is for "
     "'what's relevant to this question'. Both are populated automatically after each run."),
    (0.76, "documents",
     "Langfuse observability is configured in src/agent/tracing.py and instruments every agent "
     "run automatically via the LangChain CallbackHandler. The handler intercepts all LLM calls "
     "and tool calls within the LangGraph execution, creating spans in the Langfuse trace. Each "
     "CLI run gets a fresh CallbackHandler instance (one trace per run). The Langfuse client "
     "is a singleton initialised from settings (public key, secret key, base URL). The default "
     "base URL points to a local Langfuse instance at http://localhost:3000 — a cloud instance "
     "URL can be substituted in .env. Session ID and user ID are attached via Langfuse's "
     "propagate_attributes context manager in cli.py. Cost tracking is handled by Langfuse "
     "automatically for supported models (Gemini 2.0 Flash pricing is configured in the "
     "Langfuse dashboard model definitions)."),
    (0.73, "interactions",
     "User asked: How do I add a new tool to the agent? Agent answered: Three steps. First, "
     "create a new file in src/agent/tools/ (or add to an existing one) and decorate the "
     "function with @tool from langchain_core.tools. The function must return a string — on "
     "success return the result, on failure return 'Error: <description>' and never raise. "
     "Second, import the tool in src/agent/tools/__init__.py and add it to the ALL_TOOLS list. "
     "Third, if the tool modifies external state (creates/sends/deletes anything), add its "
     "name to TOOLS_REQUIRING_APPROVAL in graph.py so the human-in-the-loop gate catches it. "
     "The LLM will discover the tool automatically through bind_tools() — it reads the "
     "function's docstring and type annotations to build the tool schema, so write clear "
     "docstrings that explain when to use the tool and what arguments it expects."),
    (0.70, "documents",
     "The agent project structure follows a layered architecture. The interface layer is the "
     "CLI (src/agent/cli.py using sys.argv). The orchestration layer is LangGraph "
     "(src/agent/graph.py) with a ReAct loop. The LLM core is Gemini 2.0 Flash via "
     "langchain-google-genai. The tools layer contains connectors for filesystem "
     "(filesystem.py), web search (web.py), Gmail (gmail.py), Google Calendar "
     "(google_calendar.py), and memory retrieval (memory.py). The memory layer has "
     "episodic memory (episodic.py), semantic memory (semantic.py), and context budget "
     "management (budget.py). Configuration is handled by Pydantic Settings in config.py "
     "loading from .env. Authentication for Google APIs is in auth/google.py. "
     "Observability via Langfuse is in tracing.py."),
    (0.68, "interactions",
     "User asked: The agent called the wrong tool — how do I debug this? Agent answered: "
     "Start with the Langfuse trace for that run. The trace shows the full message history "
     "including the LLM's reasoning step (the AIMessage before each tool call) — this tells "
     "you what the model was thinking when it chose the wrong tool. Common causes: the tool "
     "docstring is ambiguous (the model can't tell when to use it vs. another tool), the "
     "system prompt doesn't constrain tool selection clearly enough, or the model was "
     "given too many tools at once and picked the closest match. Fix options: improve the "
     "tool's docstring with explicit 'use this when X, don't use this when Y' guidance, "
     "add a negative example to the system prompt, or temporarily remove tools that aren't "
     "needed for your use case to reduce decision noise."),
    (0.66, "documents",
     "Google OAuth2 flow for Gmail and Calendar: the first run opens a browser window for "
     "the OAuth consent screen (scope: gmail.readonly, calendar.readonly, and optionally "
     "gmail.compose and calendar.events for write access). The token is saved to "
     "credentials/token.json and auto-refreshed when expired. The google_credentials.json "
     "file (downloaded from GCP Console) must be placed at credentials/google_credentials.json "
     "before first run. Both paths are gitignored. The auth module (auth/google.py) handles "
     "token refresh transparently — if the refresh token expires (after 6 months of inactivity "
     "for personal accounts, or immediately if access is revoked), the agent returns an error "
     "string from the tool and the user must re-run the OAuth flow manually by deleting "
     "token.json and restarting the agent."),
    (0.64, "interactions",
     "User asked: How much does a typical agent run cost? Agent answered: For Gemini 2.0 Flash "
     "at current pricing ($0.075/M input tokens, $0.30/M output tokens), a typical agent run "
     "costs between $0.0001 and $0.001. A simple question answered without tools (1,000–2,000 "
     "tokens) costs roughly $0.00015. A multi-tool run that calls Gmail and Calendar (5,000–8,000 "
     "tokens total across multiple LLM calls) costs roughly $0.0005–0.0008. A complex run with "
     "semantic memory retrieval and multiple tool calls (10,000–15,000 tokens) costs around "
     "$0.001. A week of daily use (20 runs average) would cost roughly $0.01–0.02. Langfuse "
     "tracks cost per run automatically once you configure Gemini pricing in the model "
     "definitions. The episodic memory log also records cost_usd per run if you want to query "
     "historical cost data."),
    (0.63, "documents",
     "Chroma vector database is used for semantic memory, persisted at data/chroma/. Two "
     "collections are maintained: 'documents' (for user-ingested files and pages) and "
     "'interactions' (for past agent conversation pairs). Embeddings use Google's "
     "gemini-embedding-001 model (768-dimensional dense vectors). Documents are split into "
     "chunks of 500 tokens with 50-token overlap before embedding (RecursiveCharacterTextSplitter). "
     "Retrieval uses cosine similarity with a configurable score threshold (default 0.7 in "
     "settings). The SemanticMemory class provides ingest_document(), ingest_interaction(), "
     "search_documents(), search_interactions(), and search_all() methods. The search_all() "
     "method queries both collections, deduplicates by content, and returns results sorted by "
     "score descending, capped at memory_top_k results."),
    (0.62, "interactions",
     "User asked: Why does the agent sometimes not call any tools and just answer directly? "
     "Agent answered: The LLM decides whether to call a tool or answer from its training "
     "knowledge on each reasoning step. If the question can be answered confidently from "
     "what the model already knows (e.g., 'what is a Python decorator?'), it will skip "
     "tools. The system prompt says 'prefer calling a tool over speculating whenever the "
     "answer depends on the contents of a file, current information, or external state' — "
     "but the model doesn't always follow this strictly for borderline questions. If you "
     "want to force tool use for a specific type of query, you can either add a more "
     "explicit instruction to the system prompt ('ALWAYS use the web_search tool for any "
     "question about current events') or change the LLM configuration to require tool use "
     "via tool_choice parameter in the bind_tools call."),
    (0.61, "documents",
     "The Pydantic Settings class in src/agent/config.py loads all configuration from the "
     ".env file in the project root. Required fields: GOOGLE_API_KEY (Gemini), TAVILY_API_KEY "
     "(web search), LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY. Optional fields with defaults: "
     "LANGFUSE_BASE_URL (defaults to http://localhost:3000 for local Langfuse), MODEL_NAME "
     "(defaults to gemini-2.0-flash), MAX_ITERATIONS (defaults to 10), SQLITE_PATH (defaults "
     "to data/episodic.db), CHROMA_PATH (defaults to data/chroma), "
     "CHROMA_EMBEDDING_MODEL (defaults to models/gemini-embedding-001), "
     "MEMORY_SCORE_THRESHOLD (defaults to 0.7), MEMORY_TOP_K (defaults to 5), "
     "CONTEXT_WARNING_THRESHOLD (defaults to 100,000 tokens), "
     "CONTEXT_HARD_LIMIT (defaults to 800,000 tokens). Running `python -c 'from agent.config "
     "import settings; print(settings)'` verifies the configuration loads correctly."),
]


def _pad_to_min_chars(text: str, min_chars: int) -> str:
    """Extend text by appending agent-context boilerplate until it reaches min_chars.

    Used to create realistically large fixture payloads. The boilerplate text reads
    like extended agent reasoning, which is the realistic source of context bloat.
    """
    boilerplate = (
        " Additional context: Cross-referencing with the sprint backlog confirms these items "
        "align with the current planning cycle. The relevant Confluence documentation was last "
        "updated within the last 30 days and has been reviewed for accuracy. JIRA ticket "
        "priorities were validated against the resource allocation model from last sprint's "
        "retrospective. Team capacity estimates account for on-call rotations, planned leave, "
        "and cross-team dependencies flagged in the dependency tracker. All calendar events "
        "have been verified against the shared team calendar and individual schedules. "
        "The information retrieved from the tools has been cross-checked for consistency. "
        "No conflicting data was found in the episodic memory log for the past 7 days. "
        "Semantic similarity scores for retrieved memory chunks are all above the 0.7 threshold "
        "configured in the agent settings. The context budget is within acceptable limits. "
        "The agent will continue with the next reasoning step based on this information."
    )
    while len(text) < min_chars:
        text += boilerplate
    return text[:min_chars + len(boilerplate)]  # slight overshoot is fine


def generate_all(output_dir: Path | None = None) -> None:
    """Generate all three fixture files. Idempotent — safe to call multiple times."""
    out = output_dir or FIXTURES_DIR
    out.mkdir(parents=True, exist_ok=True)

    # --- 1. Long conversation ---
    # Target: >30,000 tokens from 60 messages → avg 500 tokens/msg → 2,000 chars/msg.
    # Human messages padded to 800 chars, AI messages padded to 2,400 chars.
    conversation = []
    for human_text, ai_text in _CONVERSATION_PAIRS:
        conversation.append({"role": "human", "content": _pad_to_min_chars(human_text, 800)})
        conversation.append({"role": "ai", "content": _pad_to_min_chars(ai_text, 2_800)})

    with open(out / "long_conversation.json", "w", encoding="utf-8") as f:
        json.dump(conversation, f, indent=2)

    # --- 2. Bloated tool result ---
    # Target: >15,000 tokens from the single JSON ToolMessage string.
    # 25 emails × 2,500-char body → ~62,500 chars → ~15,625 tokens.
    emails = []
    for subject, sender, date, body in _EMAIL_DATA:
        expanded_body = _pad_to_min_chars(body, 2_500)
        emails.append({
            "subject": subject,
            "sender": sender,
            "date": date,
            "snippet": body[:100] + "...",
            "body": expanded_body,
            "thread_id": f"thread_{hash(subject) & 0xFFFFFF:06x}",
            "message_id": f"msg_{hash(body) & 0xFFFFFF:06x}",
            "labels": ["INBOX", "UNREAD"],
        })

    with open(out / "bloated_tool_result.json", "w", encoding="utf-8") as f:
        json.dump(emails, f, indent=2)

    # --- 3. Large memory injection ---
    # Target: >8,000 tokens from 15 chunks → avg 533 tokens/chunk → 2,134 chars/chunk.
    memory_chunks = []
    for score, source, content in _MEMORY_CHUNKS:
        expanded_content = _pad_to_min_chars(content, 2_134)
        memory_chunks.append({
            "content": expanded_content,
            "source": source,
            "score": score,
            "metadata": {"source_type": source, "score": score},
        })

    with open(out / "large_memory_injection.json", "w", encoding="utf-8") as f:
        json.dump(memory_chunks, f, indent=2)

    print(f"Generated fixtures in {out}:")
    for name in ("long_conversation.json", "bloated_tool_result.json", "large_memory_injection.json"):
        size = (out / name).stat().st_size
        print(f"  {name}: {size:,} bytes")


if __name__ == "__main__":
    generate_all()
