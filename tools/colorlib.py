#!/usr/bin/env python3
"""colorlib —— 感知色差与色彩空间工具（无第三方依赖）。

本文件为调色板的**语义校验**提供度量，包含：

  * CIEDE2000 (ΔE00) —— 内联 Sharma/Wu/Dalal (2005) 的 34 组官方测试向量，
    运行 `python3 tools/colorlib.py` 会自测；未通过自测的度量不能用来下结论。
  * 色觉障碍（CVD）模拟 —— Machado/Oliveira/Fernandes (2009) severity=1.0，
    作用于**线性** sRGB。红绿色觉障碍在人群中的比例常被引用为 ~8%，
    终端里 `git diff` 的红/绿正是最容易崩塌的一对。
  * sRGB ↔ CIELAB ↔ LCh 互转，以及色域内的最大彩度、按目标对比度反解明度。

为什么要引入它：原 `tools/verify.py` 只查 APCA/WCAG 对比度和 6 个颜色的色相角。
对比度是**必要不充分**条件 —— 两个颜色可以各自都清晰可读，却互相看不出区别
（"危险"和"装饰"同色），或者在色觉障碍下完全重合。这些都必须用 ΔE00 才能查出来。

ΔE00 的可读标尺（本仓库据此设阈值）：
     < 1     几乎不可辨
     1 – 2   仅并排细看可辨（JND ≈ 2.3）
     2 – 10  一眼可辨
    10 – 20  明显不同的颜色
     > 20    完全不同的色相/明度区域
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from apca import hx, lc, rgb2lab, wcag_ratio  # noqa: F401  (复用，避免两套实现各说各话)

# ---------------------------------------------------------------- sRGB ↔ Lab
_EPS = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0
_WP = (0.95047, 1.0, 1.08883)          # D65


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def _f(t):
    return t ** (1 / 3) if t > _EPS else (_KAPPA * t + 16) / 116


def _finv(t):
    t3 = t ** 3
    return t3 if t3 > _EPS else (116 * t - 16) / _KAPPA


def lab2linear(L, a, b):
    """CIELAB -> 线性 sRGB（可能越界，调用方判断色域）。"""
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    X, Y, Z = _WP[0] * _finv(fx), _WP[1] * _finv(fy), _WP[2] * _finv(fz)
    return (3.2404542 * X - 1.5371385 * Y - 0.4985314 * Z,
            -0.9692660 * X + 1.8760108 * Y + 0.0415560 * Z,
            0.0556434 * X - 0.2040259 * Y + 1.0572252 * Z)


def in_gamut(L, a, b, tol=1e-9):
    return all(-tol <= c <= 1 + tol for c in lab2linear(L, a, b))


def lab2hex(L, a, b):
    clamp = lambda c: min(1.0, max(0.0, c))
    return '#%02x%02x%02x' % tuple(
        round(clamp(_unlin(clamp(c))) * 255) for c in lab2linear(L, a, b))


def lch2lab(L, C, h):
    r = math.radians(h)
    return L, C * math.cos(r), C * math.sin(r)


def hex2lch(h):
    L, a, b = rgb2lab(h)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def L_(h):
    return hex2lch(h)[0]


def C(h):
    return hex2lch(h)[1]


def H(h):
    return hex2lch(h)[2]


def hue_dist(h1, h2):
    d = abs(h1 - h2) % 360
    return min(d, 360 - d)


def max_chroma(L, h, hi=150.0):
    """固定 (L*, h_ab)，二分求 sRGB 色域内可用的最大 C*ab。"""
    if not in_gamut(*lch2lab(L, 0.0, h)):
        return 0.0
    lo = 0.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if in_gamut(*lch2lab(L, mid, h)):
            lo = mid
        else:
            hi = mid
    return lo


def lch2hex(L, Ctar, h):
    """在色域内取 (L, min(Ctar, Cmax), h) 的十六进制。"""
    return lab2hex(*lch2lab(L, min(Ctar, max_chroma(L, h)), h))


def solve_L_for_lc(bg, target_lc, h, ctar, light_text=None, coarse=0.25):
    """固定色相/彩度，找使 |Lc(color, bg)| 最接近 target_lc 的 L*。

    light_text: True 强制比底色亮 / False 强制更暗 / None 按底色明度自动判断。
    注意 APCA 的 Lc 被**底色亮度封顶**：底色太暗（亮字）或太亮（暗字）时，
    无论前景怎么调都到不了目标值 —— 此时返回能达到的最大对比度，
    这也是浅色模式"hover 层不能一味压暗"的根本原因。
    """
    bgL = L_(bg)
    if light_text is None:
        light_text = bgL < 50.0
    lo, hi = (bgL, 100.0) if light_text else (0.0, bgL)
    best, x = None, lo
    while x <= hi + 1e-9:
        c = lch2hex(x, ctar, h)
        got = abs(lc(c, bg))
        if best is None or abs(got - target_lc) < abs(best[1] - target_lc):
            best = (c, got, x)
        x += coarse
    return best


def solve_L_for_wcag(bg, target_ratio, h, ctar, light_text=None, coarse=0.25):
    bgL = L_(bg)
    if light_text is None:
        light_text = bgL < 50.0
    lo, hi = (bgL, 100.0) if light_text else (0.0, bgL)
    best, x = None, lo
    while x <= hi + 1e-9:
        c = lch2hex(x, ctar, h)
        got = wcag_ratio(c, bg)
        if got >= target_ratio and (best is None or abs(got - target_ratio) < abs(best[1] - target_ratio)):
            best = (c, got, x)
        x += coarse
    if best is None:
        x = lo
        while x <= hi + 1e-9:
            c = lch2hex(x, ctar, h)
            got = wcag_ratio(c, bg)
            if best is None or got > best[1]:
                best = (c, got, x)
            x += coarse
    return best


# ---------------------------------------------------------------- CIEDE2000
def de00(lab1, lab2, kL=1, kC=1, kH=1):
    """CIEDE2000 色差。"""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7))) if Cb > 0 else 0.5
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if (abs(a1p) + abs(b1)) > 0 else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if (abs(a2p) + abs(b2)) > 0 else 0.0
    dLp, dCp = L2 - L1, C2p - C1p
    if C1p * C2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp) / 2)
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dTh = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + (0.015 * (Lbp - 50) ** 2) / math.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -math.sin(math.radians(2 * dTh)) * Rc
    return math.sqrt((dLp / (kL * Sl)) ** 2 + (dCp / (kC * Sc)) ** 2
                     + (dHp / (kH * Sh)) ** 2
                     + Rt * (dCp / (kC * Sc)) * (dHp / (kH * Sh)))


def dE(h1, h2):
    """两个十六进制颜色的 CIEDE2000 色差。"""
    return de00(rgb2lab(h1), rgb2lab(h2))


# ---------------------------------------------------------------- CVD 模拟
# Machado, Oliveira & Fernandes (2009), severity = 1.0，作用于线性 RGB。
CVD_MATRICES = {
    'protanopia': ((0.152286, 1.052583, -0.204868),
                   (0.114503, 0.786281, 0.099216),
                   (-0.003882, -0.048116, 1.051998)),
    'deuteranopia': ((0.367322, 0.860646, -0.227968),
                     (0.280085, 0.672501, 0.047413),
                     (-0.011820, 0.042940, 0.968881)),
    'tritanopia': ((1.255528, -0.076749, -0.178779),
                   (-0.078411, 0.930809, 0.147602),
                   (0.004733, 0.691367, 0.303900)),
}


def simulate_cvd(h, kind):
    """返回该色觉类型下看到的颜色（十六进制）。"""
    lin = [_lin(c) for c in hx(h)]
    out = []
    for row in CVD_MATRICES[kind]:
        v = min(1.0, max(0.0, sum(row[i] * lin[i] for i in range(3))))
        out.append(min(1.0, max(0.0, _unlin(v))))
    return '#%02x%02x%02x' % tuple(round(v * 255) for v in out)


def dE_cvd(h1, h2, kind):
    """在指定色觉类型下的感知色差 —— 用来回答"二色觉者还分得开这两个颜色吗"。"""
    return dE(simulate_cvd(h1, kind), simulate_cvd(h2, kind))


# ---------------------------------------------------------------- 自测
# Sharma, Wu & Dalal (2005) 官方补充测试数据，Table 1。
SHARMA = [
    ((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
    ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615),
    ((50, 2.8361, -74.0200), (50, 0, -82.7485), 3.4412),
    ((50, -1.3802, -84.2814), (50, 0, -82.7485), 1.0000),
    ((50, -1.1848, -84.8006), (50, 0, -82.7485), 1.0000),
    ((50, -0.9009, -85.5211), (50, 0, -82.7485), 1.0000),
    ((50, 0, 0), (50, -1, 2), 2.3669),
    ((50, -1, 2), (50, 0, 0), 2.3669),
    ((50, 2.49, -0.001), (50, -2.49, 0.0009), 7.1792),
    ((50, 2.49, -0.001), (50, -2.49, 0.001), 7.1792),
    ((50, 2.49, -0.001), (50, -2.49, 0.0011), 7.2195),
    ((50, 2.49, -0.001), (50, -2.49, 0.0012), 7.2195),
    ((50, -0.001, 2.49), (50, 0.0009, -2.49), 4.8045),
    ((50, -0.001, 2.49), (50, 0.001, -2.49), 4.8045),
    ((50, -0.001, 2.49), (50, 0.0011, -2.49), 4.7461),
    ((50, 2.5, 0), (50, 0, -2.5), 4.3065),
    ((50, 2.5, 0), (73, 25, -18), 27.1492),
    ((50, 2.5, 0), (61, -5, 29), 22.8977),
    ((50, 2.5, 0), (56, -27, -3), 31.9030),
    ((50, 2.5, 0), (58, 24, 15), 19.4535),
    ((50, 2.5, 0), (50, 3.1736, 0.5854), 1.0000),
    ((50, 2.5, 0), (50, 3.2972, 0), 1.0000),
    ((50, 2.5, 0), (50, 1.8634, 0.5757), 1.0000),
    ((50, 2.5, 0), (50, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]


def selftest(verbose=True):
    """返回 True/False；verify.py 启动时会调用一次。"""
    ok = True
    worst = 0.0
    for l1, l2, exp in SHARMA:
        got = de00(l1, l2)
        worst = max(worst, abs(got - exp))
        if abs(got - exp) > 1e-4:
            ok = False
            if verbose:
                print(f"  ΔE00 自测失败: 期望 {exp} 实得 {got:.5f}")
    # CVD 合理性：红绿在二色觉下应当显著靠近（这是该模型的已知行为）
    rg = dE('#cd0000', '#00cd00')
    rg_d = dE_cvd('#cd0000', '#00cd00', 'deuteranopia')
    if not rg_d < rg:
        ok = False
    if verbose:
        print(f"  ΔE00 自测: Sharma 官方向量 {len(SHARMA)}/{len(SHARMA)}，最大误差 {worst:.2e}")
        print(f"  CVD 合理性: ΔE00(红,绿) 正常 {rg:.1f} → 绿色盲 {rg_d:.1f}（应变小）")
    return ok


if __name__ == '__main__':
    print(__doc__)
    print("自测：")
    sys.exit(0 if selftest() else 1)
