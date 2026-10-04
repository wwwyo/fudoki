"""五本の短冊の並びを保ち、外形と幅／空きの比率を定義する。"""
from math import sqrt

PHI = (1 + sqrt(5)) / 2
ORIGINAL = [[2, 14, 4, 14, 2], [8, 6, 4, 22, 2], [14, 18, 4, 10, 2], [20, 2, 4, 26, 2], [26, 11, 4, 17, 2], [2, 29, 28, 2, 1]]


def proportioned(width: float, height: float) -> list[list[float]]:
    """幅／空きへ黄金比を適用し、短冊の高さの並びを共通中心へ配置する。"""
    strip = width / (5 + 4 / PHI)
    gap = strip / PHI
    rule = strip / PHI
    separation = rule / PHI
    left = (32 - width) / 2
    top, base = 16.5 - height / 2, 16.5 + height / 2
    bottom = base - rule - separation
    tallest = bottom - top
    rects = []
    for index, rect in enumerate(ORIGINAL[:-1]):
        bar_height = tallest * rect[3] / 26
        rects.append([left + index * (strip + gap), bottom - bar_height, strip, bar_height, strip / 2])
    rects.append([left, base - rule, width, rule, rule / 2])
    return rects


def geometries() -> dict[str, list[list[float]]]:
    """元の比率、縦長の黄金比、外形を短くした光学調整案を返す。"""
    return {"original": ORIGINAL, "golden": proportioned(29 / PHI, 29), "compact": proportioned(26, 25)}
