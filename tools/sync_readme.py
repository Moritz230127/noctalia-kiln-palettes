#!/usr/bin/env python3
"""把 README.md 里所有**色值表格**按当前 palettes/*.json 重新生成。

README 是手写的，但里面的色值不应该手抄 —— 抄一次就会和 JSON 脱节一次。
本脚本只替换「表格里的色值」和「主色 C*ab / 底色色相」这两类数据，
叙述文字一律不动。
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
from apca import chroma, hue_ab  # noqa: E402

ROLES = [("mSurface", "底色"), ("mSurfaceVariant", "面层"), ("mHover", "悬停"),
         ("mPrimary", "主色"), ("mSecondary", "次色"), ("mTertiary", "三色"),
         ("mError", "错误"), ("mOnSurface", "文字"), ("mOutline", "边框")]
ORDER = ["汝窑", "龙泉窑", "钧窑", "建窑", "景德镇", "定窑", "越窑", "哥窑", "德化窑", "耀州窑"]


def load():
    P = {}
    for f in glob.glob('palettes/*.json'):
        P[os.path.basename(f)[:-5]] = json.load(open(f, encoding='utf-8'))
    return P


def table(P, name):
    d = P[name]
    lines = ["| 角色 | 深色 | 浅色 |", "|---|---|---|"]
    for key, zh in ROLES:
        lines.append(f"| {zh} | `{d['dark'][key]}` | `{d['light'][key]}` |")
    return "\n".join(lines)


def meta_line(P, name):
    d = P[name]
    c = chroma(d['dark']['mPrimary'])
    hd, hl = hue_ab(d['dark']['mSurface']), hue_ab(d['light']['mSurface'])
    return (f"主色 C\\*ab **{c:.1f}**（釉感指标）　·　底色色相 "
            f"**{hd:.0f}°** / **{hl:.0f}°**")


def main():
    P = load()
    src = open('README.md', encoding='utf-8').read()

    # 1) 各窑详情里的小表
    for name in ORDER:
        pat = re.compile(
            r"(### " + re.escape(name) + r"\n.*?\n)(\| 角色 \| 深色 \| 浅色 \|\n"
            r"\|[-\s|]*\|\n(?:\|[^\n]*\n)+)", re.S)
        m = pat.search(src)
        if not m:
            print(f"  ! 未找到 {name} 的角色表")
            continue
        # 只在该窑自己的小节范围内替换（用全局 count=1 会串到别的窑去 —— 实测 9/10 段 meta 行错位）
        sec_pat = re.compile(r"(### " + re.escape(name) + r"\n.*?)(?=\n### |\n## |\Z)", re.S)
        sec = sec_pat.search(src)
        if not sec:
            print(f"  ! 未找到 {name} 小节")
            continue
        body = sec.group(1)
        body = re.sub(r"\| 角色 \| 深色 \| 浅色 \|\n\|[-\s|]*\|\n(?:\|[^\n]*\n)+",
                      table(P, name) + "\n", body, count=1)
        body = re.sub(r"主色 C\\\*ab \*\*[\d.]+\*\*（釉感指标）　·　底色色相 "
                      r"\*\*\d+°\*\* / \*\*\d+°\*\*", meta_line(P, name), body, count=1)
        src = src[:sec.start(1)] + body + src[sec.end(1):]

    # 2) 十窑总览表
    def ov(m):
        name, loc = m.group(1), m.group(2)
        d = P[name]
        return (f"| **{name}** | {loc} | `{d['dark']['mSurface']}` | "
                f"`{d['dark']['mPrimary']}` | `{d['light']['mSurface']}` | "
                f"`{d['light']['mPrimary']}` | {chroma(d['dark']['mPrimary']):.1f} |")
    src = re.sub(r"\| \*\*(.+?)\*\* \| (.+?) \| `#[0-9a-f]{6}` \| `#[0-9a-f]{6}` \| "
                 r"`#[0-9a-f]{6}` \| `#[0-9a-f]{6}` \| [\d.]+ \|",
                 lambda m: ov(m), src)
    open('README.md', 'w', encoding='utf-8').write(src)
    print("README 色值表已按 palettes/ 重新生成")


if __name__ == '__main__':
    main()
