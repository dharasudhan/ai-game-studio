#!/usr/bin/env python3
"""Synthesise the studio jingle (original, code-generated, ~2.8 s) in sync with the intro timeline.
Notes follow the brand: one marimba pluck per wordmark letter (the mascot's letter is the boing), a shimmer for
the subline, a cheer slide, a sparkle chime and a final chord.  Usage: make_jingle.py [brand.json] [out_dir]
Writes jingle.ogg (Godot) and jingle.mp3 (web, Safari).  Needs numpy + ffmpeg."""
import json, os, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(HERE)
brand_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(KIT, "addons/studio_intro/brand.json")
out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(KIT, "addons/studio_intro/audio")
brand = json.load(open(brand_path))

# ---- timeline: keep in sync with studio_intro.gd
T_LAND1, T_LAND2, T_LETTER0, LETTER_GAP = 0.55, 0.92, 0.80, 0.075
T_CHEER, T_CHEER_LAND, T_SPARK, T_END = 1.62, 1.9, 1.70, 2.8

word = brand.get("wordmark", "Studio")
slot = brand.get("mascot_slot", "auto")
if slot == "auto":
    idx = [i for i, ch in enumerate(word) if ch in "oO0"]
    slot = idx[-1] if idx else -1
elif slot == "above":
    slot = -1
n_letters = len(word) - (1 if isinstance(slot, int) and 0 <= slot < len(word) else 0)
sub = brand.get("subline", "")

SR = 44100
N = int(SR * T_END)
L = np.zeros(N)
R = np.zeros(N)


def note(f):
    return 440.0 * 2 ** ((f - 69) / 12.0)


def add(sig, t0, pan=0.0, gain=1.0):
    i0 = int(t0 * SR)
    if i0 >= N:
        return
    sig = sig[: N - i0] * gain
    lg = np.cos((pan + 1) * np.pi / 4)
    rg = np.sin((pan + 1) * np.pi / 4)
    L[i0:i0 + len(sig)] += sig * lg
    R[i0:i0 + len(sig)] += sig * rg


def tt(d):
    return np.arange(int(d * SR)) / SR


def env(t, a=0.004, k=7.0):
    return np.minimum(1.0, t / a) * np.exp(-k * t)


def boing(f0, d=0.42, amp=0.5):
    t = tt(d)
    fr = f0 * (1 + 0.85 * np.exp(-5.5 * t) * np.cos(2 * np.pi * 7.5 * t))
    ph = 2 * np.pi * np.cumsum(fr) / SR
    s = np.sin(ph) + 0.25 * np.sin(2 * ph)
    thump = np.sin(2 * np.pi * 85 * t) * np.exp(-28 * t) * 0.9
    return (s * env(t, 0.003, 6.5) + thump) * amp


def marimba(f, d=0.6, amp=0.35):
    t = tt(d)
    s = np.sin(2 * np.pi * f * t) + 0.22 * np.sin(2 * np.pi * f * 3.93 * t) * np.exp(-14 * t) + 0.08 * np.sin(2 * np.pi * f * 9.2 * t) * np.exp(-30 * t)
    return s * env(t, 0.002, 6.0) * amp


def bell(f, d=1.1, amp=0.25):
    t = tt(d)
    parts = [(1, 1.0, 3.2), (2.76, 0.45, 5.0), (5.4, 0.25, 8.0), (8.93, 0.12, 12.0)]
    s = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-k * t) for r, a, k in parts if f * r < 11000)
    return s * np.minimum(1, t / 0.002) * amp


def slide(f0, f1, d, amp=0.2):
    t = tt(d)
    fr = f0 * (f1 / f0) ** (t / d)
    ph = 2 * np.pi * np.cumsum(fr) / SR
    return np.sin(ph) * np.sin(np.pi * t / d) ** 0.7 * amp


def pad(fs, d, amp=0.1):
    t = tt(d)
    s = np.zeros_like(t)
    for k, f in enumerate(fs):
        s += np.sin(2 * np.pi * f * t + k) + 0.3 * np.sin(2 * np.pi * 2 * f * t)
    e = np.minimum(1, t / 0.03) * np.exp(-2.2 * t)
    return s / len(fs) * e * amp


# drop whoosh (soft filtered noise rising) before the first landing
rng = np.random.default_rng(7)
wt = tt(0.38)
wn = rng.standard_normal(len(wt))
wn = np.convolve(wn, np.ones(24) / 24, mode="same")
add(wn * (wt / 0.38) ** 2 * 0.25, T_LAND1 - 0.38, 0.0)
add(boing(note(64), 0.45, 0.55), T_LAND1, 0.0)          # big landing boing (E4)
add(boing(note(71), 0.35, 0.32), T_LAND2, 0.1)          # smaller one in the slot (B4)
scale = [72, 74, 76, 79, 81, 84, 86, 88, 91, 93]        # C major pentatonic from C5
for j in range(n_letters):
    f = note(scale[min(j, len(scale) - 1)])
    add(marimba(f), T_LETTER0 + LETTER_GAP * j, -0.6 + 1.2 * j / max(1, n_letters - 1), 0.9)
t_sub = T_LETTER0 + LETTER_GAP * max(0, n_letters - 1) + 0.22
for k in range(min(len(sub), 8)):
    add(bell(note(84 + [0, 2, 4, 7, 9, 12, 14, 16][k]), 0.4, 0.06), t_sub + 0.035 * k, 0.5 - k * 0.12)
add(slide(520, 1150, T_CHEER_LAND - T_CHEER + 0.05, 0.11), T_CHEER - 0.02, 0.0)
add(bell(note(96), 1.1, 0.24), T_SPARK, 0.25)            # sparkle chime (C7)
add(bell(note(103), 0.8, 0.10), T_SPARK + 0.06, -0.3)
add(marimba(note(48), 1.0, 0.45), T_SPARK, 0.0)          # bass C3
add(pad([note(60), note(64), note(67), note(74)], T_END - T_SPARK, 0.22), T_SPARK, 0.0)
add(marimba(note(84), 0.9, 0.25), T_SPARK, -0.2)
add(marimba(note(88), 0.9, 0.18), T_SPARK + 0.02, 0.2)

# small room: 4 parallel feedback combs (plain loop, no scipy needed)
def comb(x, d, g):
    n = int(d * SR)
    y = x.copy()
    for i in range(n, len(x), n):
        j = min(len(x), i + n)
        y[i:j] += y[i - n:j - n] * g
    return y


def room(x):
    wet = sum(comb(x, d, g) - x for d, g in [(0.0297, 0.55), (0.0371, 0.5), (0.0411, 0.47), (0.0437, 0.44)]) / 4.0
    # soften the wet signal (one-pole low-pass) so the tails stay warm
    out = np.empty_like(wet)
    acc = 0.0
    a = 0.35
    for i in range(len(wet)):
        acc += a * (wet[i] - acc)
        out[i] = acc
    return x + out * 0.6


L2, R2 = room(L), room(R)
fade = np.ones(N)
nf = int(0.25 * SR)
fade[-nf:] = np.linspace(1, 0, nf) ** 2
st = np.stack([L2 * fade, R2 * fade], axis=1)
st /= max(1e-6, np.abs(st).max()) / 0.89
pcm = (st * 32767).astype(np.int16)

os.makedirs(out_dir, exist_ok=True)
import tempfile
wav = os.path.join(tempfile.gettempdir(), "studio_jingle.wav")
import wave
with wave.open(wav, "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libvorbis", "-q:a", "5", os.path.join(out_dir, "jingle.ogg")], check=True)
mp3_dir = sys.argv[3] if len(sys.argv) > 3 else None
if mp3_dir:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "128k", os.path.join(mp3_dir, "jingle.mp3")], check=True)
    subprocess.run(["cp", os.path.join(out_dir, "jingle.ogg"), os.path.join(mp3_dir, "jingle.ogg")], check=True)
print("jingle: %d letters, subline %r, %.2f s -> %s" % (n_letters, sub, T_END, out_dir))
