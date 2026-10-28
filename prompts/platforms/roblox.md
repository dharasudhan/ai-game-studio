# Platform track: Roblox
- Different engine: Luau, not Godot. Repo is a Rojo project (default.project.json, src/server, src/client,
  src/shared). Keep game code in Git; the owner syncs it into Roblox Studio with the Rojo plugin.
- Design for Roblox: multiplayer-first servers, short sessions, social hooks (invite, party), mobile + PC +
  console controls, retention through daily rewards and updates. Look at top experiences in the genre first.
- Code: server is the authority (never trust the client), RemoteEvents validated and rate-limited,
  DataStore saves with retries and session locking, no deprecated APIs, StreamingEnabled for big maps.
- QA: lint/format (selene, stylua) and TestEZ-style unit tests where possible; the owner runs the playtest
  in Studio (Play solo + a 2-player local server). Seen-it screenshots on phone and PC view.
- Publish: Open Cloud place-publishing API with the owner's key, ONLY after Gate 5. Maturity & Compliance
  questionnaire, experience guidelines, icon/thumbnails and description pass Roblox moderation.
- Money: Robux only (game passes, developer products, subscriptions, Premium payouts, Roblox's own rewarded ads).
  No outside links, outside payments or third-party ad SDKs. Paid random items must show their odds.
- Safety: Roblox Community Standards; all player text through TextService filtering; respect age-based
  chat and content rules; no collecting personal data.
