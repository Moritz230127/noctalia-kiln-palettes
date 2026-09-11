#!/usr/bin/env python3
"""批量校验 palettes/ 下所有调色板。

检查两类问题：
  A. 对比度 —— 每个前景/背景组合是否达到按角色设定的 APCA Lc 目标
  B. 色相撞车 —— 任意两个"双方彩度都 > 10"的强调色，色相角是否至少相差 20°

用法:  python3 tools/verify.py [调色板目录]
退出码: 0 = 全部通过, 1 = 存在失败项
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apca import lc, wcag_ratio, chroma, hue_ab  # noqa: E402

ROLES16 = ["mPrimary", "mOnPrimary", "mSecondary", "mOnSecondary", "mTertiary", "mOnTertiary",
           "mError", "mOnError", "mSurface", "mOnSurface", "mSurfaceVariant", "mOnSurfaceVariant",
           "mOutline", "mShadow", "mHover", "mOnHover"]
TERM_KEYS = ["background", "foreground", "cursor", "cursorText", "selectionBg", "selectionFg",
             "normal", "bright"]
ANSI8 = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
HEXRE = re.compile(r"#[0-9a-fA-F]{6}")

# 按角色设定的 APCA Lc 下限（正文 75 / 内容文本 60，见 README 的设计约束）
MIN_BODY, MIN_CONTENT, MIN_UI_RATIO = 75, 60, 3.0
MIN_HUE_GAP, MIN_CHROMA_FOR_HUE = 20.0, 10.0


def check_palette(path):
    """返回 (失败项列表, 统计字典)"""
    P = json.load(open(path, encoding="utf-8"))
    fails, stats = [], {}
    for mode in ("dark", "light"):
        d = P[mode]
        t = d["terminal"]
        bg, sv, hv = d["mSurface"], d["mSurfaceVariant"], d["mHover"]

        # ---- A. 结构 ----
        for k in ROLES16:
            if k not in d:
                fails.append(f"{mode}:缺角色 {k}")
        for k in TERM_KEYS:
            if k not in t:
                fails.append(f"{mode}:缺 terminal.{k}")
        for g in ("normal", "bright"):
            for k in ANSI8:
                if k not in t.get(g, {}):
                    fails.append(f"{mode}:缺 terminal.{g}.{k}")
        for v in list(d.values()) + list(t.values()):
            if isinstance(v, str) and not HEXRE.fullmatch(v):
                fails.append(f"{mode}:非法色值 {v}")

        # ---- B. 对比度 ----
        if abs(lc(d["mOnSurface"], bg)) < MIN_BODY:
            fails.append(f"{mode}:正文 {lc(d['mOnSurface'], bg):.1f}")
        if abs(lc(d["mOnSurface"], hv)) < MIN_BODY:
            fails.append(f"{mode}:正文@悬停 {lc(d['mOnSurface'], hv):.1f}")
        if abs(lc(d["mOnSurface"], sv)) < MIN_BODY:
            fails.append(f"{mode}:正文@面层 {lc(d['mOnSurface'], sv):.1f}")
        if abs(lc(d["mOnSurfaceVariant"], sv)) < MIN_CONTENT:
            fails.append(f"{mode}:次要文本@面层 {lc(d['mOnSurfaceVariant'], sv):.1f}")
        for r in ("Primary", "Secondary", "Tertiary", "Error"):
            if abs(lc(d["m" + r], sv)) < MIN_CONTENT:
                fails.append(f"{mode}:{r}@面层 {lc(d['m' + r], sv):.1f}")
            if abs(lc(d["mOn" + r], d["m" + r])) < MIN_CONTENT:
                fails.append(f"{mode}:on{r} {lc(d['mOn' + r], d['m' + r]):.1f}")
        if wcag_ratio(d["mOutline"], bg) < MIN_UI_RATIO:
            fails.append(f"{mode}:边框 {wcag_ratio(d['mOutline'], bg):.2f}:1")
        if abs(lc(t["foreground"], t["background"])) < MIN_BODY:
            fails.append(f"{mode}:终端前景 {lc(t['foreground'], t['background']):.1f}")
        if abs(lc(t["selectionFg"], t["selectionBg"])) < MIN_CONTENT:
            fails.append(f"{mode}:选区 {lc(t['selectionFg'], t['selectionBg']):.1f}")

        # ---- C. 色相撞车 ----
        items = [("主色", d["mPrimary"]), ("次色", d["mSecondary"]), ("三色", d["mTertiary"]),
                 ("错误", d["mError"]), ("终端青", t["normal"]["cyan"]),
                 ("终端紫", t["normal"]["magenta"])]
        hues = [(n, hue_ab(c), chroma(c)) for n, c in items]
        worst = 360.0
        for i in range(len(hues)):
            for j in range(i + 1, len(hues)):
                if hues[i][2] > MIN_CHROMA_FOR_HUE and hues[j][2] > MIN_CHROMA_FOR_HUE:
                    dd = abs(hues[i][1] - hues[j][1])
                    dd = min(dd, 360 - dd)
                    worst = min(worst, dd)
                    if dd < MIN_HUE_GAP:
                        fails.append(f"{mode}:色相撞车 {hues[i][0]}-{hues[j][0]} {dd:.0f}°")

        stats[mode] = {"body": abs(lc(d["mOnSurface"], bg)),
                       "variant": abs(lc(d["mOnSurfaceVariant"], sv)),
                       "hue_gap": worst if worst < 360 else None,
                       "chroma": chroma(d["mPrimary"])}
    return fails, stats


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "palettes"
    files = sorted(glob.glob(os.path.join(root, "*.json")))
    if not files:
        print(f"未找到调色板: {root}/*.json")
        return 1
    print(f"{'调色板':<12}{'模式':<7}{'正文Lc':>8}{'面层Lc':>8}{'最小色相间距':>13}{'主色彩度':>9}   状态")
    print("-" * 74)
    bad = 0
    for f in files:
        name = os.path.basename(f)[:-5]
        fails, stats = check_palette(f)
        if fails:
            bad += 1
        for mode in ("dark", "light"):
            s = stats[mode]
            gap = f"{s['hue_gap']:.0f}°" if s["hue_gap"] else "—"
            tag = "✓" if not fails else "✗ " + "; ".join(fails[:2])
            print(f"{name:<12}{mode:<7}{s['body']:>8.1f}{s['variant']:>8.1f}{gap:>13}{s['chroma']:>9.1f}   {tag}")
    print()
    if bad:
        print(f"{bad} 份调色板存在问题 ✗")
        return 1
    print(f"全部通过 ✓  （{len(files)} 份调色板 × 深/浅两种模式）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
