#!/usr/bin/env python3
"""Static, overlap-free instance of the variable brand font (MSDF needs non-overlapping contours, otherwise the
distance field shows seams inside joined strokes). Usage: make_font.py <variable.ttf> <out.ttf> [wght] [wdth]
Needs fonttools + skia-pathops (pip install fonttools skia-pathops)."""
import sys
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
src, out = sys.argv[1], sys.argv[2]
wght = float(sys.argv[3]) if len(sys.argv) > 3 else 700
wdth = float(sys.argv[4]) if len(sys.argv) > 4 else 100
f = TTFont(src)
axes = {a.axisTag: a for a in f["fvar"].axes} if "fvar" in f else {}
loc = {}
if "wght" in axes: loc["wght"] = wght
if "wdth" in axes: loc["wdth"] = wdth
inst = instancer.instantiateVariableFont(f, loc, inplace=False, overlap=instancer.OverlapMode.REMOVE)
inst.save(out)
print("font: static instance", loc, "->", out)
