#!/usr/bin/env python3
"""为每个窑口调色板生成 SVG 色卡预览（深色/浅色两行）。"""
import json, glob, os, sys

ROLES = [("mSurface","底"),("mSurfaceVariant","面层"),("mHover","悬停"),
         ("mPrimary","主色"),("mSecondary","次色"),("mTertiary","三色"),
         ("mError","错误"),("mOnSurface","字"),("mOutline","边框")]

def swatch(x, y, w, h, fill, label, sub, text_color):
    return f'''  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>
  <text x="{x+w/2}" y="{y+h/2-4}" font-size="13" fill="{text_color}" text-anchor="middle" font-family="sans-serif">{label}</text>
  <text x="{x+w/2}" y="{y+h/2+14}" font-size="10" fill="{text_color}" opacity="0.65" text-anchor="middle" font-family="monospace">{sub}</text>
'''

def build(path):
    name = os.path.basename(path)[:-5]
    P = json.load(open(path))
    W, ROW, SW = 24 + len(ROLES)*(100+6) + 24, 86, 100
    H = ROW*2 + 74
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           f'  <rect width="{W}" height="{H}" fill="#ffffff"/>',
           f'  <text x="24" y="30" font-size="17" font-weight="600" fill="#111" font-family="sans-serif">{name}</text>']
    for i, mode in enumerate(("dark","light")):
        d = P[mode]; y = 46 + i*ROW
        out.append(f'  <text x="24" y="{y+18}" font-size="11" fill="#666" font-family="sans-serif">{"深色" if mode=="dark" else "浅色"}</text>')
        x = 24
        for key, zh in ROLES:
            c = d[key]
            txt = d["mOnSurface"] if mode == "dark" else d["mOnSurface"]
            # 在色块上选可读的标注色
            import colorsys
            r,g,b = (int(c[1:][j:j+2],16)/255 for j in (0,2,4))
            lum = 0.2126*r+0.7152*g+0.0722*b
            tc = "#111111" if lum > 0.45 else "#f5f5f5"
            out.append(swatch(x, y+26, SW, 52, c, zh, c, tc))
            x += SW + 6
    out.append('</svg>')
    open(f"preview/{name}.svg","w").write("\n".join(out)+"\n")

for p in sorted(glob.glob("palettes/*.json")):
    build(p)
    print(f"  preview/{os.path.basename(p)[:-5]}.svg")
