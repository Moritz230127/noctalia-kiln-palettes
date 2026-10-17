#!/usr/bin/env python3
"""为每个窑口调色板生成 SVG 色卡预览。

三行：
  1. 深色模式的 9 个 UI 角色
  2. 浅色模式的 9 个 UI 角色
  3. **终端 16 色**（normal + bright）—— 外加一行"语义锚点"参照

第 3 行是 2026-10 补上的。原因：原预览只画 UI 角色，而 ANSI 块恰恰是问题最集中的
地方（原版把 mPrimary/mSecondary/mTertiary/mError 按位置倒进 green/blue/yellow/red）。
不画出来，光看色卡永远发现不了"green 是紫色"。
"""
import glob
import json
import os

ROLES = [("mSurface", "底"), ("mSurfaceVariant", "面层"), ("mHover", "悬停"),
         ("mPrimary", "主色"), ("mSecondary", "次色"), ("mTertiary", "三色"),
         ("mError", "错误"), ("mOnSurface", "字"), ("mOutline", "边框")]

ANSI_ORDER = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
ANSI_ZH = {"black": "黑", "red": "红", "green": "绿", "yellow": "黄",
           "blue": "蓝", "magenta": "品红", "cyan": "青", "white": "白"}
# xterm 默认 16 色 —— ANSI 槽位的语义参照（"红"应该长这样）
XTERM = {"black": "#000000", "red": "#cd0000", "green": "#00cd00", "yellow": "#cdcd00",
         "blue": "#0000ee", "magenta": "#cd00cd", "cyan": "#00cdcd", "white": "#e5e5e5"}


def lum(c):
    r, g, b = (int(c[1:][j:j + 2], 16) / 255 for j in (0, 2, 4))
    f = lambda x: x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


SW_PITCH = 106


def txt_on(c):
    return "#111111" if lum(c) > 0.28 else "#f5f5f5"


def swatch(x, y, w, h, fill, label, sub, tc=None):
    tc = tc or txt_on(fill)
    return (f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}"/>\n'
            f'  <text x="{x + w / 2}" y="{y + h / 2 - 3}" font-size="13" fill="{tc}" '
            f'text-anchor="middle" font-family="sans-serif">{label}</text>\n'
            f'  <text x="{x + w / 2}" y="{y + h / 2 + 13}" font-size="10" fill="{tc}" '
            f'opacity="0.7" text-anchor="middle" font-family="monospace">{sub}</text>\n')


def build(path):
    name = os.path.basename(path)[:-5]
    P = json.load(open(path, encoding="utf-8"))
    NCOL = len(ROLES)                      # 9 列
    PITCH, SW = SW_PITCH, 100
    W = 18 + NCOL * PITCH + 12
    UI_ROW = 80
    TERM_BLOCK = 150
    H = 46 + UI_ROW * 2 + 16 + TERM_BLOCK * 2 + 78
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}">',
           f'  <rect width="{W}" height="{H}" fill="#ffffff"/>',
           f'  <text x="18" y="30" font-size="17" font-weight="600" fill="#111" '
           f'font-family="sans-serif">{name}</text>']
    hdr = ('<text x="{x}" y="{y}" font-size="12" font-weight="600" fill="#333" '
           'font-family="sans-serif">{t}</text>')

    def row(y, label, cells, h=48):
        out.append(hdr.format(x=18, y=y, t=label))
        for k, (fill, lab, sub) in enumerate(cells):
            out.append(swatch(18 + k * PITCH, y + 6, SW, h, fill, lab, sub))

    for i, mode in enumerate(("dark", "light")):
        d = P[mode]
        y = 44 + i * UI_ROW
        row(y, "深色 UI" if mode == "dark" else "浅色 UI",
            [(d[key], zh, d[key]) for key, zh in ROLES], 46)

    y = 44 + UI_ROW * 2 + 14
    for mode, glabel in (("dark", "深色终端 normal / bright"), ("light", "浅色终端 normal / bright")):
        d = P[mode]["terminal"]
        out.append(hdr.format(x=18, y=y, t=glabel))
        for gi, grp in enumerate(("normal", "bright")):
            for k, slot in enumerate(ANSI_ORDER):
                c = d[grp][slot]
                out.append(swatch(18 + k * PITCH, y + 6 + gi * 32, SW, 30, c,
                                  ANSI_ZH[slot] if gi == 0 else "", c))
        y += TERM_BLOCK
    # 语义锚点参照（两种模式共用，放最底）
    row(y, "xterm 默认 16 色 —— ANSI 槽位的语义参照（“红”应该长这样）",
        [(XTERM[s], ANSI_ZH[s], XTERM[s]) for s in ANSI_ORDER], 30)
    out.append('</svg>')
    open(f"preview/{name}.svg", "w").write("\n".join(out) + "\n")


if __name__ == "__main__":
    os.makedirs("preview", exist_ok=True)
    for p in sorted(glob.glob("palettes/*.json")):
        build(p)
        print(f"  preview/{os.path.basename(p)[:-5]}.svg")
