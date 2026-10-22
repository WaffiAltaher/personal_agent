# 08: Google login checked at startup

**Type:** task

**Model:** Composer 2.5

**Blocked by:** 07

**Status:** claimed

**Closes:** E1, E2 (decision (j))

**What to build:** When the **real** Google tools are bound, startup checks the Google login before the run begins. If the token is missing, or refreshing it fails because the refresh token is dead (`invalid_grant`), the dead token is deleted and startup fails with a message naming the re-login command. A new re-login command logs in through the browser and saves the token; it is the only place a browser ever opens. In Fixture-world mode there is no check. The login docstring is corrected: Testing-mode refresh tokens expire seven days after issue, regardless of use.

- [ ] Test: real-mode startup with a dead refresh token deletes the token and fails with a message containing the re-login command
- [ ] Test: real-mode startup with no token fails the same way, without opening a browser
- [ ] Test: Fixture-world startup never checks the Google login
- [ ] The re-login command exists and is named in the message, the CLI docs and the project instructions
- [ ] No tool call can trigger the browser flow any more

## Notes for the implementer

Model the check on the existing MS365 login check. Trap: today the browser flow is reached from inside the first Gmail or Calendar tool call (mid-run); that path must go.

Spec: `../spec.md`. Decisions: `../findings.md` ("Decisions taken").
