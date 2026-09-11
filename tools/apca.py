#!/usr/bin/env python3
"""APCA (SAPC 0.0.98G-4g W3) + WCAG 2.x 对比度计算。

APCA 常量逐字取自官方参考实现 Myndex/apca-w3 (src/apca-w3.js, Beta 0.1.9 W3)。
符号约定：Lc 为负 = 亮字暗底 (WoB)，为正 = 暗字亮底 (BoW)。
"""

MAIN_TRC = 2.4                      # 2.4 指数，用于模拟实际显示器感知
SRCO, SGCO, SBCO = 0.2126729, 0.7151522, 0.0721750
NORM_BG, NORM_TXT = 0.56, 0.57      # G-4g 常量（BoW）
REV_TXT, REV_BG = 0.62, 0.65        # G-4g 常量（WoB）
BLK_THRS, BLK_CLMP = 0.022, 1.414   # 近黑软钳位
SCALE_BOW = SCALE_WOB = 1.14
LO_BOW_OFF = LO_WOB_OFF = 0.027
DELTA_Y_MIN, LO_CLIP = 0.0005, 0.1


def hx(h):
    """'#rrggbb' -> (r, g, b)"""
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- APCA
def apca_y(rgb):
    f = lambda c: (c / 255.0) ** MAIN_TRC
    return SRCO * f(rgb[0]) + SGCO * f(rgb[1]) + SBCO * f(rgb[2])


def lc(txt, bg):
    """返回带符号的 APCA Lc。"""
    ty, by = apca_y(hx(txt)), apca_y(hx(bg))
    ty = ty if ty > BLK_THRS else ty + (BLK_THRS - ty) ** BLK_CLMP
    by = by if by > BLK_THRS else by + (BLK_THRS - by) ** BLK_CLMP
    if abs(by - ty) < DELTA_Y_MIN:
        return 0.0
    if by > ty:                                     # 暗字亮底
        sapc = (by ** NORM_BG - ty ** NORM_TXT) * SCALE_BOW
        out = 0.0 if sapc < LO_CLIP else sapc - LO_BOW_OFF
    else:                                           # 亮字暗底
        sapc = (by ** REV_BG - ty ** REV_TXT) * SCALE_WOB
        out = 0.0 if sapc > -LO_CLIP else sapc + LO_WOB_OFF
    return out * 100.0


# ---------------------------------------------------------------- WCAG 2.x
def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def wcag_y(rgb):
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def wcag_ratio(fg, bg):
    a, b = wcag_y(hx(fg)), wcag_y(hx(bg))
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------- CIELAB
def rgb2lab(h):
    r, g, b = (_lin(c) for c in hx(h))
    X = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    Y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    Z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(X / 0.95047), f(Y / 1.0), f(Z / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def chroma(h):
    """CIELAB 彩度 C*ab —— 判断"釉感"（低彩度）与"彩感"（高彩度）的核心指标。"""
    _, a, b = rgb2lab(h)
    return (a * a + b * b) ** 0.5


def hue_ab(h):
    """CIELAB 色相角，用于检查两个颜色是否撞车。"""
    import math
    _, a, b = rgb2lab(h)
    return math.degrees(math.atan2(b, a)) % 360


if __name__ == "__main__":
    import sys
    if len(sys.argv) == 3:
        fg, bg = sys.argv[1], sys.argv[2]
        print(f"APCA  Lc {lc(fg, bg):+.1f}")
        print(f"WCAG  {wcag_ratio(fg, bg):.2f}:1")
        print(f"C*ab  {chroma(fg):.1f}   h_ab {hue_ab(fg):.1f}°")
    else:
        print(__doc__)
        print("用法: apca.py <前景 #rrggbb> <背景 #rrggbb>")
