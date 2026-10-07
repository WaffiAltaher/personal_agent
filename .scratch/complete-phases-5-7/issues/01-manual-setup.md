# 01: Manual setup (owner)

**What to build:** Everything only the owner can do, done in one sitting so the live tickets (16, 17) can run. Generate the interactive setup wizard with the `/wizard` skill, then run it. It covers:
- Informer: create an API key (Settings → API keys) and copy the security code (Settings → account).
- An Anthropic API key, for the Claude Sonnet 5.5 comparison.
- Confirm the Gemini API key works with `gemini-3.8-flash`.
- Azure app registration: grant `Mail.ReadWrite` (Graph permission to create Drafts) and confirm with `--list-permissions` against the pinned server version from ticket 05.
- The one-time MS365 `--login` with the pinned server version, keeping the token cache in the macOS keychain.
- Set the expected MS365 username.
- Start local Langfuse.
- Fill in every new `.env` setting introduced by tickets 02–15.

**Blocked by:** None (can start immediately). Best done after ticket 15 lands, so every new setting exists.

**Status:** ready-for-human

- [ ] Wizard generated and run to completion
- [ ] `.env` holds working Informer, Anthropic and Gemini credentials and the expected MS365 username
- [ ] MS365 login cached for the pinned server version; `Mail.ReadWrite` granted
- [ ] Local Langfuse reachable
