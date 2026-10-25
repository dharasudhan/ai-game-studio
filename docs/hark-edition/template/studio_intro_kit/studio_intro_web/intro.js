/* Studio intro + loading overlay for web games (three.js or anything else). No dependencies.
 * Same beat as the Godot addon: the mascot drops in, squashes, hops into its letter, the wordmark pops in
 * letter by letter, a sparkle, then it fades to the game (or to the loading screen if the game is not ready).
 *
 *   <script src="studio_intro_web/brand.js"></script>   <!-- generated from brand.json -->
 *   <script src="studio_intro_web/intro.js"></script>
 *   const ld = StudioIntro.loader({tips: ["Tip one"], colors: {bg_top: "#E8F6FF"}});   // optional, shows later
 *   StudioIntro.trackThree(THREE.DefaultLoadingManager, ld);   // three.js progress -> bar
 *   await StudioIntro.play({ready: assetsLoadedPromise, loader: ld});   // intro, then loader until ready
 *
 * Brand: window.STUDIO_BRAND (brand.js) or play({brand}). Assets (font, jingle) are loaded from `base`
 * (default: the folder this script was loaded from).
 */
(function (root) {
  "use strict";
  var T = { DROP: 0.12, LAND1: 0.55, HOP: 0.62, LAND2: 0.92, LETTER0: 0.80, GAP: 0.075, POP: 0.32,
    CHEER: 1.62, CHEER_LAND: 1.9, SPARK: 1.70, FADE: 2.35, END: 2.8, SKIP_FADE: 0.25 };
  var scriptBase = (function () {
    var s = document.currentScript && document.currentScript.src;
    return s ? s.slice(0, s.lastIndexOf("/") + 1) : "studio_intro_web/";
  })();

  function brandOf(b) {
    b = b || root.STUDIO_BRAND || {};
    var c = b.colors || {};
    var d = { bg_top: "#FFF7E8", bg_bottom: "#FFD9B8", letter: "#3A8DFF", letter_hi: "#A9D4FF", outline: "#1F2559",
      shadow: "#1F255938", subline: "#1F2559", mascot: "#FF5DA2", mascot_shade: "#D93A85", mascot_hi: "#FFC4DE",
      cheek: "#FF2E7E66", eye: "#1F2559", sparkle: "#FFD23F" };
    for (var k in c) d[k] = c[k];
    var word = b.wordmark || "Studio";
    var slot = b.mascot_slot === undefined ? "auto" : b.mascot_slot;
    if (slot === "auto") { slot = -1; for (var i = word.length - 1; i >= 0; i--) if ("oO0".indexOf(word[i]) >= 0) { slot = i; break; } }
    else if (slot === "above" || typeof slot !== "number" || slot >= word.length) slot = -1;
    return { name: b.studio_name || word, word: word, sub: b.subline || "", slot: slot, col: d,
      fontFile: b.web_font || "Fredoka-Bold.ttf", jingle: b.web_jingle || "jingle" };
  }
  // "#RRGGBBAA" -> css rgba
  function css(h, a) {
    h = h.replace("#", "");
    var r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
    var al = h.length >= 8 ? parseInt(h.substr(6, 2), 16) / 255 : 1;
    return "rgba(" + r + "," + g + "," + b + "," + (al * (a === undefined ? 1 : a)).toFixed(3) + ")";
  }
  function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }
  function easeOutBack(u, s) { u = clamp(u, 0, 1) - 1; return 1 + u * u * ((s + 1) * u + s); }
  function spring(t, t0, amp) { if (t < t0) return 0; var x = t - t0; return -amp * Math.exp(-7.5 * x) * Math.cos(27 * x); }

  function mascotState(t, h0, h1, h2, lookX) {
    if (lookX === undefined) lookX = -0.85;
    var lift = 0, q = 0, w;
    if (t < T.LAND1) { var u = clamp((t - T.DROP) / (T.LAND1 - T.DROP), 0, 1); lift = h0 * (1 - u * u); q = 0.24 * u; }
    else if (t < T.HOP) lift = 0;
    else if (t < T.LAND2) { w = (t - T.HOP) / (T.LAND2 - T.HOP); lift = h1 * 4 * w * (1 - w); }
    else if (t >= T.CHEER && t < T.CHEER_LAND) { w = (t - T.CHEER) / (T.CHEER_LAND - T.CHEER); lift = h2 * 4 * w * (1 - w); }
    q += spring(t, T.LAND1, 0.4) + spring(t, T.LAND2, 0.24) + spring(t, T.CHEER_LAND, 0.16);
    if (t > T.CHEER - 0.1 && t < T.CHEER) q -= 0.14 * Math.sin((t - (T.CHEER - 0.1)) / 0.1 * Math.PI);
    if (t >= T.CHEER && t < T.CHEER_LAND) q += 0.12 * Math.sin((t - T.CHEER) / (T.CHEER_LAND - T.CHEER) * Math.PI);
    var sy = 1 + q, sx = 1 / Math.pow(Math.max(0.3, sy), 0.65), lean = 0;
    if (t > T.LAND2) { var x = t - T.LAND2; lean = 0.24 * Math.exp(-3.2 * x) * Math.sin(15 * x); }
    var wob = 0.025;
    if (t > T.LAND1) wob += 0.08 * Math.exp(-4 * (t - T.LAND1));
    if (t > T.LAND2) wob += 0.05 * Math.exp(-4 * (t - T.LAND2));
    var look = t < T.LAND1 ? [0, 0.9] : [0, 0];
    if (t > T.LETTER0 + 0.05 && t < 1.38) look = [lookX, 0.15];
    var eye = 1;
    if (t > 1.44 && t < 1.56) eye = Math.abs((t - 1.5) / 0.06);
    if (t >= T.CHEER && t < T.CHEER_LAND + 0.18) eye = 0;
    var mouth = t < T.LAND1 ? 0.55 : Math.max(0, 1 - (t - T.LAND1) * 2.2);
    if (t >= T.CHEER - 0.02 && t < T.CHEER_LAND + 0.3) mouth = 1;
    return { vis: t >= T.DROP, lift: lift, sx: sx, sy: sy, lean: lean, wob: wob, phase: t * 13, look: look,
      eye: eye, mouth: mouth, tuft: clamp(-q * 1.8 + lean * 2.4, -1, 1) };
  }

  function ell(ctx, x, y, rx, ry, color, rot) {
    if (rx < 0.3 || ry < 0.3) return;
    ctx.beginPath(); ctx.ellipse(x, y, rx, ry, rot || 0, 0, Math.PI * 2); ctx.fillStyle = color; ctx.fill();
  }

  // the mascot, feet at (fx, fy), radius r
  function drawMascot(ctx, fx, fy, r, st, c, alpha) {
    var a = alpha === undefined ? 1 : alpha, sx = st.sx || 1, sy = st.sy || 1, lean = st.lean || 0, wob = st.wob || 0, ph = st.phase || 0;
    var lift = st.lift || 0, ow = Math.max(1.5, r * 0.085);
    if (st.shadow !== 0) { var k = clamp(1 - lift / (r * 6), 0.25, 1); ell(ctx, fx, fy + r * 0.02, r * 0.95 * sx * k, r * 0.2 * k, css(c.outline, 0.22 * a * k)); }
    var bx = fx, by = fy - lift, cx = bx, cy = by - r * sy, N = 56, pts = [];
    for (var i = 0; i < N; i++) {
      var an = Math.PI * 2 * i / N, ca = Math.cos(an), sa = Math.sin(an);
      var rr = r * (1 + wob * (0.55 * Math.sin(3 * an + ph) + 0.45 * Math.sin(2 * an - ph * 1.3)));
      var yy = sa * rr * sy * (1 + 0.06 * Math.max(sa, 0)), xx = ca * rr * sx * (1 + 0.05 * Math.max(sa, 0));
      xx += lean * (-(yy - r * sy)) * 0.5;
      pts.push([cx + xx, cy + yy]);
    }
    function path(p, sc, oy) {
      ctx.beginPath();
      for (var j = 0; j < p.length; j++) { var X = cx + (p[j][0] - cx) * sc, Y = cy + (p[j][1] - cy) * sc + oy; if (j) ctx.lineTo(X, Y); else ctx.moveTo(X, Y); }
      ctx.closePath();
    }
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    // tuft
    var top = [cx + lean * r * sy * 0.5, cy - r * sy * 0.98], tf = st.tuft || 0;
    var tip = [top[0] + r * (0.16 + 0.35 * tf), top[1] - r * (0.42 - 0.06 * Math.abs(tf)) * clamp(sy, 0.6, 1.4)];
    var dx = tip[0] - top[0], dy = tip[1] - top[1], dl = Math.hypot(dx, dy) || 1, nx = -dy / dl, ny = dx / dl, tw = r * 0.17;
    ctx.beginPath();
    for (var s1 = 0; s1 <= 14; s1++) { var u1 = s1 / 14, bend = Math.sin(u1 * Math.PI) * r * 0.12, w1 = tw * (1 - u1) * (0.6 + 0.4 * u1);
      var px = top[0] + dx * u1 + nx * (bend + w1), py = top[1] + dy * u1 + ny * (bend + w1); if (s1) ctx.lineTo(px, py); else ctx.moveTo(px, py); }
    for (var s2 = 14; s2 >= 0; s2--) { var u2 = s2 / 14, bend2 = Math.sin(u2 * Math.PI) * r * 0.12, w2 = tw * (1 - u2) * (0.6 + 0.4 * u2);
      ctx.lineTo(top[0] + dx * u2 + nx * (bend2 - w2), top[1] + dy * u2 + ny * (bend2 - w2)); }
    ctx.closePath();
    ctx.strokeStyle = css(c.outline, a); ctx.lineWidth = ow * 1.6; ctx.stroke();
    ctx.fillStyle = css(c.mascot_hi, a); ctx.fill();
    ell(ctx, tip[0], tip[1], ow * 1.6, ow * 1.6, css(c.outline, a));
    ell(ctx, tip[0], tip[1], ow * 0.85, ow * 0.85, css(c.mascot_hi, a));
    // body
    path(pts, 1, 0);
    ctx.strokeStyle = css(c.outline, a); ctx.lineWidth = ow * 2; ctx.stroke();
    var g = ctx.createLinearGradient(0, cy - r * sy, 0, cy + r * sy);
    g.addColorStop(0, css(c.mascot_hi, a)); g.addColorStop(0.5, css(c.mascot, a)); g.addColorStop(1, css(c.mascot_shade, a));
    ctx.fillStyle = g; ctx.fill();
    path(pts, 0.78, -r * 0.06 * sy); ctx.fillStyle = css(c.mascot_hi, 0.22 * a); ctx.fill();
    // face
    var fcx = cx + lean * r * sy * 0.25, fcy = cy + r * 0.08 * sy, eo = clamp(st.eye === undefined ? 1 : st.eye, 0, 1), look = st.look || [0, 0];
    [-1, 1].forEach(function (sg) {
      var ex = fcx + sg * r * 0.33 * sx, ey = fcy - r * 0.12 * sy, erx = r * 0.2 * sx, ery = r * 0.25 * sy;
      if (eo > 0.12) {
        ell(ctx, ex, ey, erx + ow * 0.6, ery * eo + ow * 0.6 * eo, css(c.outline, a));
        ell(ctx, ex, ey, erx, ery * eo, "rgba(255,255,255," + a + ")");
        var pcx = ex + look[0] * erx * 0.38, pcy = ey + look[1] * ery * 0.3 * eo + ery * 0.08 * eo;
        ell(ctx, pcx, pcy, erx * 0.7, ery * 0.7 * eo, css(c.eye, a));
        ell(ctx, pcx - erx * 0.22, pcy - ery * 0.26 * eo, erx * 0.24, ery * 0.22 * eo, "rgba(255,255,255," + a + ")");
        ell(ctx, pcx + erx * 0.2, pcy + ery * 0.22 * eo, erx * 0.1, ery * 0.09 * eo, "rgba(255,255,255," + 0.8 * a + ")");
      } else {
        ctx.beginPath(); ctx.arc(ex, ey + ery * 0.2, erx * 0.85, Math.PI * 1.12, Math.PI * 1.88);
        ctx.strokeStyle = css(c.eye, a); ctx.lineWidth = ow * 1.3; ctx.stroke();
      }
      ell(ctx, ex + sg * r * 0.1 * sx, ey + r * 0.33 * sy, r * 0.15 * sx, r * 0.085 * sy, css(c.cheek, a));
    });
    var m = clamp(st.mouth || 0, 0, 1), mx = fcx, my = fcy + r * 0.24 * sy;
    if (m < 0.15) {
      ctx.beginPath(); ctx.arc(mx, my - r * 0.06 * sy, r * 0.13 * sx, Math.PI * 0.15, Math.PI * 0.85);
      ctx.strokeStyle = css(c.eye, a); ctx.lineWidth = ow * 1.1; ctx.stroke();
    } else {
      var mw = r * (0.13 + 0.05 * m) * sx, mh = r * (0.06 + 0.13 * m) * sy;
      ctx.beginPath(); ctx.ellipse(mx, my, mw, mh, 0, 0, Math.PI); ctx.closePath(); ctx.fillStyle = css(c.eye, a); ctx.fill();
      ell(ctx, mx, my + mh * 0.62, mw * 0.55, mh * 0.3, "rgba(255,115,140," + a + ")");
    }
    ell(ctx, cx - r * 0.45 * sx, cy - r * 0.5 * sy, r * 0.2 * sx, r * 0.12 * sy, "rgba(255,255,255," + 0.75 * a + ")", -0.6);
    ell(ctx, cx - r * 0.22 * sx, cy - r * 0.7 * sy, r * 0.055, r * 0.05, "rgba(255,255,255," + 0.8 * a + ")");
  }

  function sparkle(ctx, x, y, size, k, rot, col) {
    if (k <= 0.01) return;
    var s = size * k;
    ell(ctx, x, y, s * 0.55, s * 0.55, css(col, 0.22 * k));
    ctx.beginPath();
    for (var i = 0; i < 8; i++) { var an = rot + Math.PI * 2 * i / 8, rr = i % 2 ? s * 0.22 : s; var X = x + Math.cos(an) * rr, Y = y + Math.sin(an) * rr; if (i) ctx.lineTo(X, Y); else ctx.moveTo(X, Y); }
    ctx.closePath(); ctx.fillStyle = css(col, Math.min(1, k * 1.5)); ctx.fill();
    ell(ctx, x, y, s * 0.12, s * 0.12, "rgba(255,255,255," + Math.min(1, k * 1.5) + ")");
  }

  function font(px) { return "700 " + px + "px StudioBrand, 'Fredoka', 'Arial Rounded MT Bold', system-ui, sans-serif"; }

  function layout(ctx, B, box) {
    var ref = 100, adv = [], total = 0;
    ctx.font = font(ref);
    var caps = B.word === B.word.toUpperCase(), track = caps ? 0.08 * ref : 0;
    for (var i = 0; i < B.word.length; i++) { var a = (i === B.slot ? (caps ? 0.95 : 0.9) * ref : ctx.measureText(B.word[i]).width * 1.01) + track; adv.push(a); total += a; }
    var portrait = box.h > box.w;
    var s = ref * box.w * (portrait ? 0.8 : 0.56) / Math.max(1, total);
    s = Math.min(s, box.h * (portrait ? 0.2 : 0.3));
    if (B.slot < 0) s = Math.min(s, box.h * 0.16);
    var k = s / ref, x = box.x + box.w / 2 - total * k / 2, xs = [];
    for (var j = 0; j < adv.length; j++) { xs.push(x + adv[j] * k / 2); x += adv[j] * k; }
    var blockH = s * (B.slot >= 0 ? 1.15 : 2.2);
    return { s: s, xs: xs, base: box.y + box.h / 2 + blockH / 2 - s * 0.38 };
  }

  function drawLogo(ctx, t, box, alpha, B) {
    if (alpha <= 0.001) return;
    var c = B.col, L = layout(ctx, B, box), s = L.s, base = L.base, ol = s * 0.15, j = 0, lastPop = T.LETTER0, farTop = null, farD = -1;
    ctx.lineJoin = "round"; ctx.textBaseline = "alphabetic"; ctx.textAlign = "center";
    ctx.font = font(Math.round(s));
    for (var i = 0; i < B.word.length; i++) {
      if (i === B.slot) continue;
      var t0 = T.LETTER0 + T.GAP * j; lastPop = t0; j++;
      var u = (t - t0) / T.POP;
      if (u <= 0) continue;
      var sc = easeOutBack(u, 2.6), la = clamp(u * 4, 0, 1) * alpha, rot = (1 - clamp(u, 0, 1)) * (j % 2 === 0 ? 0.35 : -0.35);
      var dy = (1 - easeOutBack(u, 1.4)) * s * 0.28, ch = B.word[i];
      var dsl = B.slot >= 0 ? Math.abs(L.xs[i] - L.xs[B.slot]) : j;
      if (dsl > farD) { farD = dsl; var side = B.slot >= 0 && L.xs[i] > L.xs[B.slot] ? 1 : -1; farTop = [L.xs[i] + side * ctx.measureText(ch).width * 0.4, base - s * 0.72]; }
      ctx.save(); ctx.translate(L.xs[i], base + dy); ctx.rotate(rot); ctx.scale(sc, sc);
      ctx.lineWidth = ol;
      ctx.strokeStyle = css(c.shadow, la); ctx.fillStyle = css(c.shadow, la);
      ctx.strokeText(ch, 0, s * 0.07); ctx.fillText(ch, 0, s * 0.07);
      ctx.strokeStyle = css(c.outline, la); ctx.strokeText(ch, 0, 0);
      ctx.fillStyle = css(c.letter_hi, la); ctx.fillText(ch, 0, -s * 0.022);
      ctx.fillStyle = css(c.letter, la); ctx.fillText(ch, 0, s * 0.012);
      ctx.restore();
    }
    if (B.sub) {
      var ss = s * 0.3, track = ss * 0.32, ws = [], w = 0;
      ctx.font = font(Math.round(ss)); ctx.textAlign = "left";
      for (var k = 0; k < B.sub.length; k++) { var cw = ctx.measureText(B.sub[k]).width; ws.push(cw); w += cw + track; }
      w -= track;
      var x = box.x + box.w / 2 - w / 2, sb = base + s * (B.word === B.word.toUpperCase() ? 0.5 : 0.64), t1 = lastPop + 0.22;
      for (k = 0; k < B.sub.length; k++) {
        var u2 = (t - (t1 + 0.035 * k)) / 0.3;
        if (u2 > 0) {
          var a2 = clamp(u2 * 3, 0, 1) * alpha, dy2 = (1 - easeOutBack(u2, 1.8)) * ss * 0.9;
          ctx.lineWidth = Math.max(2, ss * 0.12); ctx.strokeStyle = "rgba(255,255,255," + 0.9 * a2 + ")"; ctx.strokeText(B.sub[k], x, sb + dy2);
          ctx.fillStyle = css(c.subline, a2); ctx.fillText(B.sub[k], x, sb + dy2);
        }
        x += ws[k] + track;
      }
    }
    var r = B.slot >= 0 ? s * 0.37 : s * 0.55;
    var fx = B.slot >= 0 ? L.xs[B.slot] : box.x + box.w / 2, fy = B.slot >= 0 ? base : base - s * 0.95;
    var st = mascotState(t, fy - box.y + r * 2.6, s * 0.62, s * 0.22, B.slot >= 0 && B.slot < B.word.length / 2 ? 0.85 : -0.85);
    if (st.vis) drawMascot(ctx, fx, fy, r, st, c, alpha);
    var su = (t - T.SPARK) / 0.55;
    if (su > 0 && su < 1) {
      sparkle(ctx, fx + r, fy - r * 2.3 - st.lift, r * 0.85, Math.pow(Math.sin(su * Math.PI), 0.8) * alpha, su * 2, c.sparkle);
      for (var d = 0; d < 6; d++) { var an = -Math.PI / 2 + (d - 2.5) * 0.55, dist = r * (1.2 + su * 1.3);
        ell(ctx, fx + Math.cos(an) * dist, fy - r - st.lift + Math.sin(an) * dist, r * 0.07 * (1 - su), r * 0.07 * (1 - su), css(c.sparkle, (1 - su) * alpha)); }
    }
    var su2 = (t - (T.SPARK + 0.12)) / 0.5;
    if (su2 > 0 && su2 < 1 && farTop) sparkle(ctx, farTop[0], farTop[1], r * 0.5, Math.pow(Math.sin(su2 * Math.PI), 0.8) * alpha, -su2 * 1.6, c.sparkle);
  }

  function makeCanvas(z) {
    var cv = document.createElement("canvas");
    cv.style.cssText = "position:fixed;left:0;top:0;width:100vw;height:100vh;height:100dvh;z-index:" + z + ";touch-action:none;transition:opacity .25s;";
    return cv;
  }
  function fit(cv) {
    var dpr = Math.min(root.devicePixelRatio || 1, 2.5), w = cv.clientWidth || innerWidth, h = cv.clientHeight || innerHeight;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    return { w: w, h: h, dpr: dpr };
  }
  var _safe = null;
  function safeBox(w, h) {
    if (!_safe) {
      _safe = document.createElement("div");
      _safe.style.cssText = "position:fixed;visibility:hidden;pointer-events:none;padding:env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);";
      document.body.appendChild(_safe);
    }
    var cs = getComputedStyle(_safe), t = parseFloat(cs.paddingTop) || 0, r = parseFloat(cs.paddingRight) || 0, b = parseFloat(cs.paddingBottom) || 0, l = parseFloat(cs.paddingLeft) || 0;
    return { x: l, y: t, w: w - l - r, h: h - t - b };
  }
  function bg(ctx, w, h, top, bottom) {
    var g = ctx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, css(top)); g.addColorStop(1, css(bottom));
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  }
  var fontReady = null;
  function loadFont(B, base) {
    if (fontReady) return fontReady;
    if (!root.FontFace) return (fontReady = Promise.resolve());
    var f = new FontFace("StudioBrand", "url(" + base + B.fontFile + ")", { weight: "100 900" });
    fontReady = Promise.race([f.load().then(function (ff) { document.fonts.add(ff); }).catch(function () {}), new Promise(function (r) { setTimeout(r, 1500); })]);
    return fontReady;
  }

  /* ---------------------------------------------------------------- loading overlay */
  function loader(opts) {
    opts = opts || {};
    var B = brandOf(opts.brand), c = {};
    for (var k in B.col) c[k] = B.col[k];
    var theme = { bg_top: B.col.bg_top, bg_bottom: B.col.bg_bottom, bar: B.col.sparkle, bar_bg: "#FFFFFF99", bar_outline: B.col.outline, title: B.col.outline, tip: B.col.outline };
    var oc = opts.colors || {};
    for (k in oc) theme[k] = oc[k];
    for (k in (opts.mascot || {})) c[k] = opts.mascot[k];
    var tips = opts.tips || [], title = opts.title || "Loading", minShow = opts.minDisplay === undefined ? 0.4 : opts.minDisplay;
    var cv = null, ctx, raf = 0, shownAt = 0, prog = 0, target = 0, clock = 0, last = 0, tipI = tips.length ? Math.floor(Math.random() * tips.length) : 0, tipT = 0, visible = false;
    function frame(now) {
      var dt = Math.max(0, Math.min(0.1, (now - last) / 1000 || 0)); last = now; clock += dt;
      prog = Math.min(target, prog + Math.max(0, target - prog) * Math.min(1, dt * 9) + dt * 0.02);
      if (tips.length > 1 && (tipT += dt) > 3.6) { tipT = 0; tipI++; }
      var f = fit(cv); ctx.setTransform(f.dpr, 0, 0, f.dpr, 0, 0);
      bg(ctx, f.w, f.h, theme.bg_top, theme.bg_bottom);
      var box = safeBox(f.w, f.h), m = Math.min(box.w, box.h), portrait = box.h > box.w, barY = box.y + box.h * (portrait ? 0.6 : 0.66), cx = box.x + box.w / 2;
      for (var i = 0; i < 7; i++) {
        var fx = ((0.13 + 0.17 * i + clock * 0.012 * (1 + 0.3 * (i % 3))) % 1.2) - 0.1, fy = 0.15 + 0.7 * ((0.37 * i * i + 0.11) % 1) + 0.02 * Math.sin(clock * 0.7 + i);
        ell(ctx, f.w * fx, f.h * fy, m * (0.06 + 0.035 * (i % 4)), m * (0.06 + 0.035 * (i % 4)), "rgba(255,255,255,0.12)");
      }
      var r = m * 0.105, P = 0.64, tau = clock % P, air = 0.46, lift = 0, q = 0;
      if (tau < air) { var w = tau / air; lift = r * 1.1 * 4 * w * (1 - w); q = 0.1 * Math.sin(w * Math.PI); }
      else { var g = tau - air; q = -0.28 * Math.exp(-11 * g) * Math.cos(26 * g) * (1 - g / (P - air)); }
      var sy = 1 + q;
      drawMascot(ctx, cx, barY - m * 0.11, r, { lift: lift, sy: sy, sx: 1 / Math.pow(Math.max(0.3, sy), 0.65), wob: 0.03 + 0.03 * Math.abs(q), phase: clock * 9,
        look: [0, 0.55], eye: (clock % 2.7) > 2.58 ? 0 : 1, mouth: 0, tuft: clamp(-q * 2 + Math.sin(clock * 6) * 0.15, -1, 1) }, c, 1);
      var ts = clamp(m * 0.06, 16, 90);
      ctx.font = font(Math.round(ts)); ctx.textAlign = "left"; ctx.lineJoin = "round";
      var tw = ctx.measureText(title + "...").width, txt = title + ".".repeat(Math.floor((clock * 2.5) % 4));
      ctx.lineWidth = ts * 0.2; ctx.strokeStyle = "rgba(255,255,255,0.85)"; ctx.strokeText(txt, cx - tw / 2, barY - m * 0.025);
      ctx.fillStyle = css(theme.title); ctx.fillText(txt, cx - tw / 2, barY - m * 0.025);
      var bw = Math.min(box.w * 0.72, m * 1.25), bh = Math.max(10, m * 0.045), bx = cx - bw / 2, by = barY + m * 0.02, ow = Math.max(2, bh * 0.16);
      function rr(x, y, w2, h2, col) { var rad = h2 / 2; ctx.beginPath(); ctx.moveTo(x + rad, y); ctx.arcTo(x + w2, y, x + w2, y + h2, rad); ctx.arcTo(x + w2, y + h2, x, y + h2, rad); ctx.arcTo(x, y + h2, x, y, rad); ctx.arcTo(x, y, x + w2, y, rad); ctx.closePath(); ctx.fillStyle = col; ctx.fill(); }
      rr(bx - ow, by - ow, bw + ow * 2, bh + ow * 2, css(theme.bar_outline));
      rr(bx, by, bw, bh, css(theme.bg_bottom)); rr(bx, by, bw, bh, css(theme.bar_bg));
      var fw = Math.max(bh, bw * clamp(prog, 0, 1));
      rr(bx, by, fw, bh, css(theme.bar)); rr(bx + bh * 0.25, by + bh * 0.16, Math.max(0, fw - bh * 0.5), bh * 0.26, "rgba(255,255,255,0.45)");
      if (tips.length) {
        var fs = clamp(m * 0.045, 14, 64); ctx.font = "600 " + Math.round(fs) + "px StudioBrand, 'Fredoka', system-ui, sans-serif"; ctx.textAlign = "center"; ctx.fillStyle = css(theme.tip);
        var words = String(tips[tipI % tips.length]).split(" "), line = "", y = by + bh + m * 0.085 + fs, maxW = Math.min(box.w * 0.84, m * 1.5);
        for (var n = 0; n < words.length; n++) { var test = line ? line + " " + words[n] : words[n]; if (ctx.measureText(test).width > maxW && line) { ctx.fillText(line, cx, y); line = words[n]; y += fs * 1.25; } else line = test; }
        if (line) ctx.fillText(line, cx, y);
      }
      raf = requestAnimationFrame(frame);
    }
    var api = {
      show: function () {
        if (visible) return api;
        visible = true;
        loadFont(B, opts.base || scriptBase);
        if (!cv) { cv = makeCanvas(opts.zIndex || 99998); ctx = cv.getContext("2d"); cv.style.opacity = "0"; document.body.appendChild(cv); }
        cv.style.display = "block"; cv.style.pointerEvents = "auto";
        requestAnimationFrame(function () { cv.style.opacity = "1"; });
        shownAt = performance.now(); last = shownAt; prog = target = 0;
        cancelAnimationFrame(raf); raf = requestAnimationFrame(frame);
        return api;
      },
      setProgress: function (p) { target = Math.max(target, clamp(p, 0, 1)); return api; },
      done: function () {
        if (!visible) return Promise.resolve();
        target = 1;
        var wait = Math.max(0, minShow * 1000 - (performance.now() - shownAt));
        return new Promise(function (res) {
          setTimeout(function () {
            visible = false; cv.style.opacity = "0"; cv.style.pointerEvents = "none";
            setTimeout(function () { if (!visible) { cancelAnimationFrame(raf); cv.style.display = "none"; } res(); }, 260);
          }, wait);
        });
      },
      get visible() { return visible; }
    };
    if (opts.show) api.show();
    return api;
  }

  /* ---------------------------------------------------------------- intro */
  function play(opts) {
    opts = opts || {};
    var B = brandOf(opts.brand), base = opts.base || scriptBase, skipAfter = opts.skipAfter === undefined ? 0.5 : opts.skipAfter;
    return loadFont(B, base).then(function () {
      return new Promise(function (resolve) {
        var cv = makeCanvas(opts.zIndex || 99999), ctx = cv.getContext("2d");
        cv.style.transition = "none";
        document.body.appendChild(cv);
        var t = 0, last = performance.now(), fadeAt = T.FADE, fadeLen = T.END - T.FADE, paused = false, ended = false, audio = null;
        if (opts.sound !== false) {
          try {
            var probe = document.createElement("audio");
            var ext = probe.canPlayType('audio/ogg; codecs="vorbis"') ? "ogg" : "mp3";
            audio = new Audio(base + B.jingle + "." + ext);
            audio.volume = opts.volume === undefined ? 0.8 : opts.volume;
            var pr = audio.play(); if (pr && pr.catch) pr.catch(function () {});   // autoplay may be blocked: silent intro
          } catch (e) { audio = null; }
        }
        function skip() {
          if (ended || t < skipAfter || t >= fadeAt) return;
          fadeAt = t; fadeLen = T.SKIP_FADE;
          if (audio) { var a0 = audio.volume, s0 = performance.now(); (function fade() { var k = (performance.now() - s0) / 250; audio.volume = Math.max(0, a0 * (1 - k)); if (k < 1) requestAnimationFrame(fade); else audio.pause(); })(); }
        }
        cv.addEventListener("pointerdown", function (e) { e.preventDefault(); skip(); });
        function onKey(e) { if (e.key === "Enter" || e.key === " " || e.key === "Escape") skip(); }
        root.addEventListener("keydown", onKey);
        function onVis() {
          if (document.hidden) { paused = true; if (audio) audio.pause(); }
          else if (paused) { paused = false; last = performance.now(); if (audio) audio.pause(); if (t < fadeAt) { fadeAt = t; fadeLen = T.SKIP_FADE; } }
        }
        document.addEventListener("visibilitychange", onVis);
        function finish() {
          ended = true;
          root.removeEventListener("keydown", onKey); document.removeEventListener("visibilitychange", onVis);
          var ready = opts.ready ? Promise.resolve(opts.ready) : Promise.resolve();
          var settled = false;
          ready.then(function () { settled = true; });
          // let a promise that is already resolved settle before deciding on the loading screen
          setTimeout(function () {
            if (!settled && opts.loader) {
              opts.loader.show();
              cv.style.transition = "opacity .3s"; cv.style.opacity = "0";
              setTimeout(function () { cv.remove(); }, 320);
              ready.then(function () { return opts.loader.done(); }).then(function () { resolve(); });
            } else {
              ready.then(function () {
                cv.style.transition = "opacity .3s"; cv.style.opacity = "0";
                setTimeout(function () { cv.remove(); resolve(); }, 320);
              });
            }
          }, 0);
          if (opts.onDone) opts.onDone();
        }
        function frame(now) {
          var dt = Math.max(0, Math.min(0.05, (now - last) / 1000)); last = now;
          if (!paused) t += dt;
          var f = fit(cv); ctx.setTransform(f.dpr, 0, 0, f.dpr, 0, 0);
          bg(ctx, f.w, f.h, B.col.bg_top, B.col.bg_bottom);
          var a = 1;
          if (t > fadeAt) { a = clamp(1 - (t - fadeAt) / Math.max(0.01, fadeLen), 0, 1); a = a * a; }
          drawLogo(ctx, opts.freezeAt !== undefined ? opts.freezeAt : t, safeBox(f.w, f.h), a, B);
          if (opts.freezeAt === undefined && t >= fadeAt + fadeLen) { finish(); return; }
          requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
      });
    });
  }

  /* three.js LoadingManager -> loader bar. Works with THREE.DefaultLoadingManager or your own manager. */
  function trackThree(manager, ld) {
    var prev = manager.onProgress;
    manager.onProgress = function (url, loaded, total) { if (ld) ld.setProgress(total ? loaded / total : 0); if (prev) prev(url, loaded, total); };
    return new Promise(function (res) { var p2 = manager.onLoad; manager.onLoad = function () { if (ld) ld.setProgress(1); if (p2) p2(); res(); }; });
  }

  root.StudioIntro = { play: play, loader: loader, trackThree: trackThree, drawLogo: drawLogo, drawMascot: drawMascot, timeline: T, brand: brandOf };
})(window);
