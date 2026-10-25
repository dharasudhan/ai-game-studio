# Compliance gate (Compliance agent) — run before every Gate 5 (store upload)
Not legal advice; Murali decides, lawyer for anything binding or high-risk.

## Every game
1. Audience: set Play target age 13+ unless deliberately for kids. If kids could be a target (cute art, simple play), either join Families policy (Families-certified ad SDKs, no personalised ads, child-directed AdMob tags) or add neutral age screen. Ads: tag under-age-of-consent users (TFUA) if age unknown.
2. GDPR/ePrivacy: Google UMP consent before ads; no tracking before consent; consent re-openable from Settings.
3. No remote fonts/scripts/CDNs at runtime; everything bundled (Godot default). Web builds: self-host fonts.
4. No session replay / analytics SDKs without consent and input masking.
5. Privacy policy hosted at public URL, matches Play Data safety form + SDK list (AdMob, Billing).
6. Content rating (IARC) questionnaire filled honestly.
7. Third-party assets: licence checked, credits.md + in-game credits (e.g. "Scenario" CC BY 4.0).
8. IAP/subscriptions: price, renewal and cancel terms beside the buy button; EU 14-day withdrawal wording for digital content; no dark patterns, loot-box odds shown.
9. EU DSA trader status in Play Console (monetised = trader; address/phone/email shown publicly — use business address if possible).
10. Marketing email (if ever): unsubscribe link + postal address. Accounts/sign-up (if ever): age gate, delete-account path (Play requirement).
11. Trademarks: game name and landmarks checked; no real brand logos.
12. Accessibility basics and Play target API deadline.
Log result per game in games/<slug>/compliance.md; blockers go to approvals.md.

## Launch-readiness audit (standing rule, Murali Oct 25 2026: "make it a habit for all apps developed")
Before EVERY closed-test or production upload of ANY studio app, QA + Compliance run the full audit and give Murali a PDF report:
- Performance: startup time, FPS per graphics tier, memory, APK/AAB size, battery/thermal notes.
- Device compatibility: min/target SDK, ABIs (64-bit), 16 KB page alignment, screen sizes/aspect ratios, GL/renderer, orientation.
- Google Play policy: target API, permissions + declarations (AD_ID, foreground service), Families/target audience, ads policy, Billing, Data safety, privacy policy URL, IARC, store listing metadata, DSA trader, closed-test rule.
- Compliance: this 12-point checklist above (COPPA/GDPR/consent, licences/credits, IAP terms).
- Verdict per item PASS/FAIL/TODO with fix, blockers first. Saved to games/<slug>/audit/launch_audit_v<version>.pdf.
