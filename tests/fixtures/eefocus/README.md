# EEFocus source-design fixtures, revision 3

**64 synthetic design cases. No production adapter or integration tests were executed.**

V3 closes two review gaps:

1. Same-origin numeric HTTP200 details now require checkable main-event identity evidence. Case 37 no longer uses an input identity_verified flag; cases 41–46 and 59 cover unrelated/missing identities, conflicting anchors, insufficient corroboration, sidebar noise, and fresh-cache contradiction
2. A current cancelled listing with expired/failed identity refresh can remove an already stored scheduled event from upcoming through a separate durable safety-only eligibility guard. It cannot admit/rekey records, assert authoritative cancellation, or delete favorites/holds/alias history

Cases 47–64 cover the cancellation lifecycle and boundaries: scheduled and favorite state, failed refresh, repeat/restart behavior, unknown/ambiguous historical targets, explicit reinstatement, retained manual holds, disassociation recovery, captured-observation replay, identical-new-fetch ambiguity, concurrency and cancellation-language scope. Safety-only counts are deliberately separate from admitted items and event content changes.

The input v2 directory and its 83 files are preserved byte-for-byte; baseline-v2.json records every actual input file and hash (the validator asserts its recorded file count). Cases 01–36 and 38–40 retain their v2 input/expected semantics. Read CONTRACT.md for the mandatory evidence obligations and strengthened R2 plus new R7–R8 implementation work.

## Files

- cases.json: all 64 cases and input/expected references
- fixtures/: original synthetic HTML and state/evidence objects
- expected/: partial semantic acceptance oracles, not complete production result objects
- CONTRACT.md / CHANGE_AUDIT.md: decisions, implementation boundaries and rationale
- provenance.json: inherited six exact source blob identities plus locally rechecked line anchors; no new remote revision verified
- baseline-v2.json: input preservation evidence
- validate_fixtures.py / validation.json: structural/evidence consistency checks only
- SHA256SUMS.txt: SHA-256 of every pack file other than the manifest itself

Run python3 validate_fixtures.py inside the directory, then sha256sum -c SHA256SUMS.txt. The validator uses only the Python standard library, performs no network request or application import, and emits stable validation metadata. Expected states are assertions about future behavior, not proof that behavior exists. A future isolated harness must run real parser/transport/worker/database/query/restart/concurrency tests before implementation acceptance.

The baseline fixed clock remains 2026-10-02 11:00 +08:00; lifecycle steps explicitly supply their later observation times. All route IDs and detail/status DOM are synthetic and not live-validated. No publisher fetches, production access, adapter deployment, repository edits, GUI operations or remote commands are included.
