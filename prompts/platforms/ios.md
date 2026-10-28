# Platform track: iOS (App Store)
- Engine: Godot 4.7.x, same GDScript code as Android where possible. Export preset "iOS" produces an Xcode
  project; building, signing and uploading need the owner's Mac with Xcode (the version Apple currently requires).
- Money first: Apple Developer Program is $99/year, which is Gate 4 before any iOS work that needs it.
- Build: bundle id com.ottranstudios.<slug>, build number bumped every upload, signed by the owner in Xcode
  (never by you). Test on device through TestFlight (internal testers need no review; external testers need beta review).
- QA: same headless Godot checks, then seen-it screenshots at iPhone portrait size (1290x2796) incl. the notch
  and home-indicator safe areas.
- Store: App Store Connect listing, App Privacy labels matching every SDK, PrivacyInfo.xcprivacy privacy
  manifest, age rating questionnaire, EU DSA trader status, support URL and privacy policy URL.
- Rules that differ from Android: digital goods and unlocks only through Apple IAP; App Tracking Transparency
  prompt before any tracking/personalised ads; Sign in with Apple if any other social login is offered;
  account deletion in-app if accounts exist; no mentions of other platforms or outside payment links.
- Money: AdMob works on iOS (needs the ATT prompt + SKAdNetwork ids), StoreKit for IAP.
