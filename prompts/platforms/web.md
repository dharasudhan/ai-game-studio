# Platform track: Web (browser)
- Engine: Godot 4.7.x HTML5 export (single-threaded unless the host sends COOP/COEP headers) or a light
  JS engine for tiny games. Mobile browsers and desktop, touch + mouse + keyboard.
- Hosting: ottranstudios.com/<slug>/ (Cloudflare Pages) and/or portals such as Poki, CrazyGames, itch.io.
  Each portal has its own SDK, ad rules and size limits: read the portal's current developer docs first.
- Performance: small first download (aim under 20 MB, show the Ottran loader at once), load under 5 s on
  4G, 60 fps on a mid-range phone, pause audio until the first tap (browser autoplay rules).
- QA: headless Godot checks, export, then open the page in a real browser and keep seen-it screenshots at
  phone portrait and 1920x1080.
- Compliance: everything self-hosted (no Google Fonts/CDN), cookie/consent banner before any ad or
  analytics cookie, privacy policy link on the page, portal SDK handles ads (no extra ad networks).
- Publishing to a portal or a public URL is Gate 6 (public) and Gate 5 (release).
