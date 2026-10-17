#!/usr/bin/env python3
"""批量校验 palettes/ 下所有调色板（语义约束 v2）。

相对 v1 的变化 —— 每一条都对应一个**实际存在过**的缺陷：

  v1 只查两件事：若干固定色对的 |APCA Lc|，以及 6 个颜色的色相角间距。
  结果是 20/20 全绿，同时 67% 的终端槽位名不副实。以下检查是补上那些盲区：

  R1  正文 APCA，并**校验极性**（v1 对所有对取 abs()，极性颠倒也会通过）
  R2  次要文本 / 强调色在面层上的 |Lc|，以及 on- 色
  R3  边框 WCAG ≥ 3:1 对 surface、variant、hover **三者**（v1 只对 surface，
      实测 20/20 套对 hover 不达标）
  R4  4 个 UI 强调色两两 ΔE00（v1 只查色相角，且被低彩度色绕过）
  R5  mError 色相必须落在危险红族 —— "错误"不能是装饰色
  R6  终端 ANSI 色相锚定（硬槽 ±15° / 软槽 ±30°）+ 彩度下限
      —— v1 最大的缺陷：ANSI 槽位是按位置倒进 mPrimary/mError 的
  R7  终端**全部 16 色**（含 bright）相对底色的可读性
  R8  bright 组不得比 normal 更暗/更灰（v1 完全不查 bright）
  R9  浅色面层不得接近纯白、深色底色不得接近纯黑
  R10 骨架层次（面层/悬停 vs 底色）的 ΔE00 下限
  R11 色觉障碍（protan/deutan）下仍需可分的配对
  R12 ANSI 彩槽两两 ΔE00 —— 终端里不能有两个几乎同色的槽

用法:  python3 tools/verify.py [调色板目录] [-v]
退出码: 0 = 全部通过, 1 = 存在失败项, 2 = 存在警告
"""
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apca import lc, wcag_ratio, chroma as C, hue_ab as H   # noqa: E402
from colorlib import dE, dE_cvd, selftest, L_, hue_dist, max_chroma  # noqa: E402

ROLES16 = ["mPrimary", "mOnPrimary", "mSecondary", "mOnSecondary", "mTertiary", "mOnTertiary",
           "mError", "mOnError", "mSurface", "mOnSurface", "mSurfaceVariant", "mOnSurfaceVariant",
           "mOutline", "mShadow", "mHover", "mOnHover"]
TERM_KEYS = ["background", "foreground", "cursor", "cursorText", "selectionBg", "selectionFg",
             "normal", "bright"]
ANSI8 = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]
HEXRE = re.compile(r"#[0-9a-fA-F]{6}")
ACCENTS = ("mPrimary", "mSecondary", "mTertiary", "mError")

# ---- 约束常量（括号内是取值依据，不是拍脑袋）-------------------------------
MIN_BODY_DARK, MIN_BODY_LIGHT = 75.0, 85.0     # APCA 正文下限 75
BODY_LC_DARK_MAX = 92.0                        # 暗色模式正文上限（超过会光晕）
MIN_CONTENT, MIN_UI_RATIO = 60.0, 3.0          # APCA 内容文本线；WCAG 1.4.11 非文本 3:1
MIN_ACCENT_DE = 10.0                           # 装饰色之间：ΔE00≥10 即"明显不同的颜色"
MIN_ACCENT_DE_ERR = 14.0                       # 错误色 vs 其它强调色，要求更严
MIN_ACCENT_HUE, MIN_ACCENT_LC = 22.0, 60.0
ERROR_HUE = (5.0, 40.0)                        # 危险红族
CVD_ACCENT_DE = 6.5                            # v1 实测最低 3.2（≈1.4×JND，等于同色）；重建后 ≥6.8

# ANSI 语义锚点 = xterm 默认 16 色在 CIELAB 下的 h_ab（事实标准的语义契约）。
# 注意：CIELAB 里 sRGB 蓝原色的 h_ab 是 306°，不是直觉色轮的 265°。
ANCHOR = {'red': 40.0, 'green': 136.0, 'yellow': 102.9,
          'blue': 303.0, 'magenta': 328.2, 'cyan': 196.4}
HARD_SLOTS = ('red', 'green', 'yellow', 'blue')
SOFT_SLOTS = ('magenta', 'cyan')
HARD_TOL, SOFT_TOL = 15.0, 30.0
# 可读性下限按模式校准：深色底可以要求 WCAG 4.5；浅色底若强求 4.5，彩度会被压到
# 无法分辨（实测 Solarized Light 只有 2.93:1、xterm 默认色在白底上低至 1.70:1）。
ANSI_WCAG_MIN = {'dark': 4.5, 'light': 3.0}
ANSI_LC_MIN = {'dark': 38.0, 'light': 48.0}
# 参照校准：xterm 默认色自身最小两两 ΔE00 = 22.1（但在 C*ab≈90 下取得），
# 釉色调色板的 ANSI 彩度只有 30–46，同样的色相间隔在低彩度下 ΔE00 天然更小。
# 浅色终端受 WCAG 下限挤压，明度阶梯被压进更窄的带（深色 ~43 |Lc|，浅色 ~23），
# 相邻色相槽的 ΔE00 上限随之下降 —— 浅底终端的固有取舍。
MIN_ANSI_DE = {'dark': 11.0, 'light': 9.0}
MIN_ANSI_C = {'dark': 26.0, 'light': 12.0}
ANSI_CVD_MIN = {'dark': 9.0, 'light': 5.5}    # 对照：xterm 19.6 / Solarized Light 5.8

MIN_LAYER_DE = 6.0                             # 骨架层之间（JND≈2.3 的 ~2.6 倍）
LIGHT_VAR_MAX_L, DARK_SURF_MIN_L = 97.5, 6.0   # 不用纯黑／纯白


def check_palette(path):
    """返回 (失败项, 警告项, 统计)"""
    P = json.load(open(path, encoding="utf-8"))
    fails, warns, stats = [], [], {}
    for mode in ("dark", "light"):
        d = P[mode]
        t = d["terminal"]
        bg, sv, hv = d["mSurface"], d["mSurfaceVariant"], d["mHover"]
        is_dark = mode == "dark"
        F = lambda m: fails.append(f"{mode}:{m}")      # noqa: E731 硬约束
        W = lambda m: warns.append(f"{mode}:{m}")      # noqa: E731
        S = lambda m: warns.append(f"{mode}:{m}")      # noqa: E731 软裕度（感知分离余量）

        # ---- A. 结构 ----
        n_before = len(fails)
        for k in ROLES16:
            if k not in d:
                F(f"缺角色 {k}")
        for k in TERM_KEYS:
            if k not in t:
                F(f"缺 terminal.{k}")
        for g in ("normal", "bright"):
            for k in ANSI8:
                if k not in t.get(g, {}):
                    F(f"缺 terminal.{g}.{k}")
        for v in list(d.values()) + list(t.values()):
            if isinstance(v, str) and not HEXRE.fullmatch(v):
                F(f"非法色值 {v}")
        if len(fails) > n_before:
            stats[mode] = _empty_stats()
            continue

        # ---- R1 正文（含极性）----
        want_pos = not is_dark
        floor = MIN_BODY_DARK if is_dark else MIN_BODY_LIGHT
        # 各层的可达上限不同：APCA 的 |Lc| 被底色亮度封顶（浅底 hover L*≈87 时
        # 再黑也只能到 ~84），所以对非主阅读层用 APCA 正文线 75 而不是 85。
        for lbl, b, lim in (("底色", bg, floor), ("面层", sv, floor), ("悬停", hv, MIN_BODY_DARK)):
            v = lc(d["mOnSurface"], b)
            if abs(v) < lim:
                F(f"正文@{lbl} Lc={v:+.1f} < {lim:.0f}")
            # 暗色模式还有**上限**：超过 −90 会光晕（README 早已声称，初版工具从未实现）
            if is_dark and abs(v) > BODY_LC_DARK_MAX:
                F(f"正文@{lbl} Lc={v:+.1f} 超过暗色上限 −{BODY_LC_DARK_MAX:.0f}（会光晕）")
            if (v > 0) != want_pos:
                F(f"正文@{lbl} 极性错误 Lc={v:+.1f}")

        # ---- R2 次要文本与强调色 ----
        for lbl, b in (("面层", sv), ("悬停", hv)):
            v = lc(d["mOnSurfaceVariant"], b)
            if abs(v) < MIN_CONTENT:
                F(f"次要文本@{lbl} Lc={v:+.1f} < {MIN_CONTENT:.0f}")
            if (v > 0) != want_pos:
                F(f"次要文本@{lbl} 极性错误 Lc={v:+.1f}")
        for r in ACCENTS:
            for lbl, b, lim in (("面层", sv, MIN_ACCENT_LC), ("悬停", hv, 48.0)):
                a = lc(d[r], b)
                if abs(a) < lim:
                    (F if lbl == "面层" else S)(f"{r}@{lbl} Lc={a:+.1f} < {lim:.0f}")
                if (a > 0) != want_pos:
                    F(f"{r}@{lbl} 极性错误 Lc={a:+.1f}")
            o = lc(d["mOn" + r[1:]], d[r])
            if abs(o) < MIN_CONTENT:
                F(f"mOn{r[1:]} Lc={o:+.1f} < {MIN_CONTENT:.0f}")

        # ---- R2b mOnHover（在 ROLES16 里，初版从未被查过）----
        vm = lc(d["mOnHover"], hv)
        if abs(vm) < MIN_CONTENT:
            F(f"mOnHover@悬停 Lc={vm:+.1f} < {MIN_CONTENT:.0f}")
        if (vm > 0) != want_pos:
            F(f"mOnHover@悬停 极性错误 Lc={vm:+.1f}")

        # ---- R3 边框对三个底色 ----
        for lbl, b in (("surface", bg), ("variant", sv), ("hover", hv)):
            rr = wcag_ratio(d["mOutline"], b)
            if rr < MIN_UI_RATIO:
                F(f"边框/{lbl} {rr:.2f}:1 < {MIN_UI_RATIO}")

        # ---- R4 强调色两两可分 ----
        worst, worst_pair = 999.0, None
        for i in range(len(ACCENTS)):
            for j in range(i + 1, len(ACCENTS)):
                a, b = ACCENTS[i], ACCENTS[j]
                de = dE(d[a], d[b])
                lim = MIN_ACCENT_DE_ERR if "mError" in (a, b) else MIN_ACCENT_DE
                if de / lim < worst:
                    worst, worst_pair = de / lim, f"{a[1:]}~{b[1:]}"
                if de < lim:
                    S(f"强调色分离余量 {a[1:]}~{b[1:]} ΔE00={de:.1f} < {lim:.0f}")
                if C(d[a]) > 8 and C(d[b]) > 8 and hue_dist(H(d[a]), H(d[b])) < MIN_ACCENT_HUE:
                    S(f"强调色相间距 {a[1:]}~{b[1:]} {hue_dist(H(d[a]), H(d[b])):.0f}° "
                      f"< {MIN_ACCENT_HUE:.0f}°")

        # ---- R5 错误色的语义 ----
        eh = H(d["mError"])
        if not (ERROR_HUE[0] <= eh <= ERROR_HUE[1]):
            F(f"mError 色相 {eh:.0f}° 不在危险红族 [{ERROR_HUE[0]:.0f},{ERROR_HUE[1]:.0f}]")

        # ---- R6/R7/R8/R12 终端 ANSI ----
        # R8 只对**彩色槽**要求「bright 的 |Lc| 更高」。black/white 是无彩槽，
        # 浅色模式下 black 是文字色、bright.black 是更淡的灰 —— 语义相反，硬套会误报。
        for slot in HARD_SLOTS + SOFT_SLOTS:
            hx_ = t["normal"][slot]
            tol = HARD_TOL if slot in HARD_SLOTS else SOFT_TOL
            dev = hue_dist(H(hx_), ANCHOR[slot])
            if dev > tol:
                F(f"ANSI {slot} 色相偏离语义锚点 {dev:.0f}° > ±{tol:.0f}°（h={H(hx_):.0f}°）")
            if C(hx_) < MIN_ANSI_C[mode]:
                F(f"ANSI {slot} 彩度 {C(hx_):.1f} < {MIN_ANSI_C[mode]:.1f}（实为灰色，无色相语义）")
            body_lc = lc(hx_, t["background"])
            if abs(body_lc) < ANSI_LC_MIN[mode]:
                F(f"ANSI {slot} 对终端底色 Lc={body_lc:+.1f} < {ANSI_LC_MIN[mode]:.0f}")
            if wcag_ratio(hx_, t["background"]) < ANSI_WCAG_MIN[mode]:
                F(f"ANSI {slot} WCAG {wcag_ratio(hx_, t['background']):.2f}:1 "
                  f"< {ANSI_WCAG_MIN[mode]}")
            hb = t["bright"][slot]
            b_lc = lc(hb, t["background"])
            if abs(b_lc) < abs(body_lc) - 2:
                F(f"ANSI bright.{slot} Lc={b_lc:+.1f} 不如 normal（{body_lc:+.1f}）")
            # 彩度判据必须按**各自的色域上限**：高 |Lc| 下色域装不下那么多彩度是物理事实。
            # 实测（h=196.4 青）：|Lc|=78 → L*84.0，上限 46.8；|Lc|=87 → L*89.0，上限 49.1 ——
            # 单看这条并不单调，真正卡住的是具体槽位（建窑 dark bright.cyan 的 C*ab 29.31
            # 恰好等于它自己的色域上限）。要求 bright 的绝对彩度 ≥ normal，会逼出
            # "压低 normal 去迁就 bright"这种把可用彩度白白扔掉的错误修法。
            # 判据：bright 至少要用掉「它自己色域上限」与「normal 彩度」中较小者的 80%。
            if C(hb) < 0.80 * min(C(hx_), max_chroma(L_(hb), H(hb))):
                F(f"ANSI bright.{slot} 彩度 {C(hb):.1f} 明显低于其色域可用值"
                  f"（normal {C(hx_):.1f}，本处上限 {max_chroma(L_(hb), H(hb)):.1f}）")
        v = lc(t["foreground"], t["background"])
        if abs(v) < MIN_BODY_DARK:
            F(f"终端 foreground Lc={v:+.1f} < {MIN_BODY_DARK:.0f}")
        # 全部 16 色：彩槽已在上面查过；这里补 black/white 与所有 bright 槽。
        #   「文字槽」（暗色的 white、浅色的 black、bright.white/black）要有真实对比度；
        #   「背景槽」（暗色的 black、浅色的 white）本就该贴近底色，只要求可区分。
        for grp, kind in (("normal", "normal"), ("bright", "bright")):
            for slot in ("black", "white"):
                c = t[grp][slot]
                lcv = lc(c, t["background"])
                text_slot = (slot == "white") if is_dark else (slot == "black")
                if grp == "bright":
                    text_slot = slot in ("white", "black")
                lim = 45.0 if text_slot else 1.10
                if text_slot:
                    if abs(lcv) < lim:
                        F(f"终端 {grp}.{slot} Lc={lcv:+.1f} < {lim:.0f}")
                elif wcag_ratio(c, t["background"]) < lim:
                    F(f"终端 {grp}.{slot} 与底色几乎相同（WCAG "
                      f"{wcag_ratio(c, t['background']):.3f}:1 < {lim}）")
        # v1 的浅色 bright.white 压在底色上 |Lc| = 0（10/10 套隐形）
        bw = lc(t["bright"]["white"], t["background"])
        if abs(bw) < 30:
            F(f"终端 bright.white 对底色 |Lc|={abs(bw):.1f} < 30（近乎隐形）")
        sl = lc(t["selectionFg"], t["selectionBg"])
        if abs(sl) < MIN_CONTENT:
            F(f"终端选区 Lc={sl:+.1f} < {MIN_CONTENT:.0f}")
        if wcag_ratio(t["selectionBg"], t["background"]) < 1.09:
            W(f"终端选区底色与底色几乎相同（WCAG "
              f"{wcag_ratio(t['selectionBg'], t['background']):.3f}:1）")
        slots = [(s, t["normal"][s]) for s in HARD_SLOTS + SOFT_SLOTS]
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                de = dE(slots[i][1], slots[j][1])
                if de < MIN_ANSI_DE[mode]:
                    S(f"ANSI 分离余量 {slots[i][0]}~{slots[j][0]} ΔE00={de:.1f} "
                      f"< {MIN_ANSI_DE[mode]:.0f}")

        # ---- R13 阴影必须是阴影 ----
        # 这条规则是被一次真实 bug 逼出来的：light mShadow 曾被写成饱和深黄
        # （#a77f00，C*ab 35–64），因为把色相角当 b* 传给了 lab2hex。
        sh = d["mShadow"]
        if is_dark:
            if L_(sh) > 30:
                F(f"深色 mShadow L*={L_(sh):.1f} 太亮，不像阴影")
        else:
            if C(sh) > 20 or L_(sh) > 70:
                F(f"浅色 mShadow {sh} 不是中性暗色（L*={L_(sh):.1f} C*ab={C(sh):.1f}）")

        # ---- R14 v1 兼容：6 色色相间距 ≥ 20° ----
        # 这条是原仓库 verify.py 的核心规则。在初版里它是**空转**的（`green` 就是
        # `mPrimary` 本身，等于自己跟自己比）；ANSI 与 UI 解耦后才第一次真正生效。
        # 必须放进校验器：优化器里虽然有对应约束，但"算得对、验不出来"意味着
        # 任何人手工微调或换一次重建都可能悄悄破坏它，而 CI 全绿。
        six = [("主色", d["mPrimary"]), ("次色", d["mSecondary"]), ("三色", d["mTertiary"]),
               ("错误", d["mError"]), ("终端青", t["normal"]["cyan"]),
               ("终端紫", t["normal"]["magenta"])]
        for i in range(len(six)):
            for j in range(i + 1, len(six)):
                if C(six[i][1]) > 10 and C(six[j][1]) > 10:
                    gap = hue_dist(H(six[i][1]), H(six[j][1]))
                    if gap < 20.0:
                        F(f"v1 规则：{six[i][0]}~{six[j][0]} 色相间距 {gap:.1f}° < 20°")

        # ---- R9 不用纯黑／纯白 ----
        if is_dark and L_(bg) < DARK_SURF_MIN_L:
            F(f"深色底色 L*={L_(bg):.1f} < {DARK_SURF_MIN_L}（接近纯黑）")
        if not is_dark and L_(sv) > LIGHT_VAR_MAX_L:
            F(f"浅色面层 L*={L_(sv):.1f} > {LIGHT_VAR_MAX_L}（接近纯白）")

        # ---- R10 骨架层次 ----
        de_sv, de_sh = dE(sv, bg), dE(hv, bg)
        if de_sv < MIN_LAYER_DE:
            S(f"面层/底色 ΔE00={de_sv:.2f} < {MIN_LAYER_DE}（ΔL*={abs(L_(sv) - L_(bg)):.1f}）")
        if de_sh < MIN_LAYER_DE:
            S(f"悬停/底色 ΔE00={de_sh:.2f} < {MIN_LAYER_DE}（ΔL*={abs(L_(hv) - L_(bg)):.1f}）")

        # ---- R11 色觉障碍 ----
        cvd = {k: dE_cvd(d["mError"], d["mPrimary"], k)
               for k in ("protanopia", "deuteranopia")}
        if min(cvd.values()) < CVD_ACCENT_DE:
            S(f"色觉障碍下 mError~mPrimary ΔE00={min(cvd.values()):.1f} < {CVD_ACCENT_DE:.0f}")
        acvd = min(dE_cvd(t["normal"]["red"], t["normal"]["green"], k)
                   for k in ("protanopia", "deuteranopia"))
        if acvd < ANSI_CVD_MIN[mode]:
            S(f"终端 red~green 在色觉障碍下 ΔE00={acvd:.1f} < {ANSI_CVD_MIN[mode]}")

        stats[mode] = {"body": abs(lc(d["mOnSurface"], bg)),
                       "outline": min(wcag_ratio(d["mOutline"], b) for b in (bg, sv, hv)),
                       "accent": worst, "accent_pair": worst_pair,
                       "ansi_dev": max(hue_dist(H(t["normal"][s]), ANCHOR[s])
                                       for s in HARD_SLOTS + SOFT_SLOTS),
                       "ansi_cvd": acvd, "layer_v": de_sv, "layer_h": de_sh,
                       "L_var": L_(sv), "L_bg": L_(bg)}
    return fails, warns, stats


def _empty_stats():
    return {"body": 0.0, "outline": 0.0, "accent": 0.0, "accent_pair": "—",
            "ansi_dev": 0.0, "ansi_cvd": 0.0, "layer_v": 0.0, "layer_h": 0.0,
            "L_var": 0.0, "L_bg": 0.0}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    root = args[0] if args else "palettes"
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    files = sorted(glob.glob(os.path.join(root, "*.json")))
    if not files:
        print(f"未找到调色板: {root}/*.json")
        return 1
    print("度量自检：")
    if not selftest():
        print("  ✗ 度量自检未通过，结果不可信，中止。")
        return 1
    print()
    print(f"{'调色板':<10}{'模式':<7}{'正文':>7}{'边框':>7}{'强调裕度':>10}"
          f"{'ANSI偏差':>9}{'CVD红绿':>9}{'层ΔE*面':>9}{'层ΔE*悬':>9}   状态")
    print("-" * 100)
    nfail = nwarn = 0
    details = {}
    for f in files:
        name = os.path.basename(f)[:-5]
        fails, warns, stats = check_palette(f)
        nfail += 1 if fails else 0
        nwarn += 1 if warns else 0
        if fails or warns:
            details[name] = (fails, warns)
        for mode in ("dark", "light"):
            s = stats[mode]
            tag = "✗" if fails else ("⚠" if warns else "✓")
            print(f"{name:<10}{mode:<7}{s['body']:>7.1f}{s['outline']:>7.2f}"
                  f"{s['accent']:>10.2f}{s['ansi_dev']:>8.0f}°{s['ansi_cvd']:>9.1f}"
                  f"{s['layer_v']:>9.2f}{s['layer_h']:>9.2f}   {tag}")
    print()
    if details and (verbose or nfail):
        for name, (fails, warns) in details.items():
            print(f"── {name}")
            for m in fails[:12]:
                print(f"   ✗ {m}")
            if len(fails) > 12:
                print(f"   ✗ …另有 {len(fails) - 12} 项")
            for m in warns:
                print(f"   ⚠ {m}")
        print()
    if nfail:
        print(f"{nfail} 份调色板存在问题 ✗  （{len(files)} 份 × 深/浅两种模式）")
        return 1
    if nwarn:
        print(f"{nwarn} 份调色板有警告 ⚠")
        return 2
    print(f"全部通过 ✓  （{len(files)} 份调色板 × 深/浅两种模式；R1–R12 全部满足）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
