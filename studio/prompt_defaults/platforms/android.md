# Platform track: Android (Google Play)
- Engine: Godot 4.7.x, GDScript, portrait. Repo from the Godot template (export preset "Android").
- Build: signed release AAB (owner's upload key, never yours), versionCode bumped every upload, target SDK 36,
  arm64-v8a, 16 KB page alignment. Debug APK for owner device tests.
- QA: headless import + unit tests + 120-frame smoke, then the seen-it screenshot at 1080x2340.
- Store: Play Console listing, JPEG screenshots, Data safety, IARC rating, Advertising ID declaration, EU DSA
  trader info. Personal account: closed test with 12 testers for 14 days before production. Review up to 7 days.
- Money: AdMob (test IDs until just before production, UMP consent first, max ad rating G), Play Billing for IAP.
