# Platform track: Web (browser)
- Engine: small 2D web games default to melonJS (github.com/melonjs/melonJS, MIT, about 250 KB, WebGPU/WebGL2/
  Canvas2D, Tiled maps, WebAudio). Bundle it from npm or the repo, never load it from a CDN. Credit it in
  CREDITS.md. Use the Godot 4.7.x HTML5 export only for 3D, for heavy games, or for a port of an existing
  Godot game. It is single-threaded unless the host sends COOP/COEP headers.
- Mobile browsers and desktop, touch + mouse + keyboard.
- Hosting: ottranstudios.com/<slug>/ (Cloudflare Pages) and/or portals such as Poki, CrazyGames, itch.io.
  Each portal has its own SDK, ad rules and size limits: read the portal's current developer docs first.
- Performance: small first download (aim under 20 MB, show the Ottran loader at once), load under 5 s on
  4G, 60 fps on a mid-range phone, pause audio until the first tap (browser autoplay rules).
- QA (automatic since 1.7.0, for games with an index.html and no project.godot): headless Chrome plays the
  page with a scripted set of taps and keys on a simulated clock, with Math.random seeded. It fails the change
  on an uncaught error, a blank canvas, input that changes nothing, or text under 12 px, off screen or
  overlapping, and it saves a phone-size screenshot. The same seed and input run on main too, so Gate 3 says
  which frames moved. Engineers: keep index.html in the repo root (or web/, public/, dist/), put a
  `studio_play.json` in the root when the game needs its own input script
  ({"steps": [{"at": 1500, "tap": [0.5, 0.5]}, {"at": 2200, "key": "ArrowRight", "hold": 500}], "budget_ms": 9000}),
  and expose `window.__studio_state = () => ({score, level, ...})` so the replay compares game state as well as
  frames. Never read time from anything but performance.now/Date.now/requestAnimationFrame, or the replay drifts.
  Godot HTML5 exports keep the Godot QA path.
- Compliance: everything self-hosted (no Google Fonts/CDN), cookie/consent banner before any ad or
  analytics cookie, privacy policy link on the page, portal SDK handles ads (no extra ad networks).
- Publishing to a portal or a public URL is Gate 6 (public) and Gate 5 (release).
