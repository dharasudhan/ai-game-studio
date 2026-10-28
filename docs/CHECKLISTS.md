# Studio checklists (folded in from the Hark edition, October 2026)

These are the lessons from shipping Ferry Out, Crumbellion and the other Ottran Studios games. The agents' prompts
(`prompts/*.md`), the Godot template (`studio/templates/godot/`) and the launch audit (`studio/audit.py`) enforce
them; this page is the human-readable version.

## Every game
- [ ] Package id `com.ottranstudios.<slug>` (never `com.studio.<slug>` or `com.<slug>.game`). Decide it before the
      first Play upload: a published package id can never change.
- [ ] Ottran Studios intro + loading screen wired (`addons/studio_intro`, main scene = intro, `StudioLoader` autoload).
- [ ] Public contact `ottranstudios@gmail.com`; website `https://ottranstudios.com` on the listing.
- [ ] Premium, modern visuals: show 2-3 style mockups before building the art. Plan the leanest path to a closed test.
- [ ] `CREDITS.md` + in-game credits for every third-party asset (fonts OFL, CC BY attributions).

## Engineering (Godot 4.7.x)
- [ ] Research before building: look at actively maintained, clearly licensed open-source projects first; credit reuse.
- [ ] Headless tests + 120-frame smoke run pass before a build reaches Gate 3.
- [ ] Lists scroll by touch with a custom drag-scroll (ScrollContainer breaks with `emulate_mouse_from_touch=false`).
- [ ] Moving units/boats follow a route planner, with a headless test over every route.
- [ ] Objects keep consistent sizes across scenes.
- [ ] Save migrations whenever content or save structure changes.

## Source control
- [ ] One private GitHub repo per game. The studio commits locally; you push.
- [ ] Never commit keys, keystores, passwords, `.env` or builds. Run `./run.sh scan games/<slug>` before every push.
- [ ] Push diffs as single, small commits.

## Launch-readiness audit (blocks Gate 5)
Runs automatically after the release build, or from Games > Actions > **Run launch audit**. PDF in
`games/<slug>/audit/launch_audit_v<version>.pdf`, blockers first. Automated checks: package prefix, versionCode
bump, target SDK 36, arm64, no keystore secrets in the preset, secret scan, intro kit, privacy policy URL live and
naming the final package id, contact email, CREDITS.md, UMP consent when ads are present, JPEG screenshots, release
QA. The QA agent adds performance, device compatibility, Play policy and compliance judgment items.

## Compliance (every store upload)
- [ ] Target audience 13+ (not Families) unless the game is for kids; AdMob max ad content rating G.
- [ ] Google UMP consent before any ad; consent re-openable in Settings.
- [ ] Advertising ID declared in Play Console when the AdMob SDK is included.
- [ ] Data safety form matches the SDKs and the privacy policy.
- [ ] Privacy policy hosted, URL in the game and the listing, naming the final package id (redeploy after a change: Gate 6).
- [ ] EU DSA trader details in Play Console. IARC questionnaire answered honestly.

## Google Play
- [ ] Personal developer account: 12 testers opted in for 14 days on a closed test before production (Google Group list).
- [ ] AAB signed with the upload key (yours, never committed), versionCode bumped, target SDK 36.
- [ ] Screenshots exported as JPEG (the store asset picker rejected PNG); feature graphic 1024x500.
- [ ] Plan for review taking up to 7 days.

## Social and marketing
- [ ] Anything public waits at Gate 6.
- [ ] Instagram via the Meta (Instagram Graph) API, not browser automation. The X API is paid: Gate 4 first.
