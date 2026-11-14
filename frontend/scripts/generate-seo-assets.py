# -*- coding: utf-8 -*-
"""生成 SEO 静态图片：frontend/public/og-image.png（1200x630）与 apple-touch-icon.png（180x180）。

用法（在 frontend 目录下）：
    python scripts/generate-seo-assets.py

依赖：Pillow；中文字体使用 Windows 微软雅黑（msyhbd.ttc）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = ROOT / "public"
FONT_PATH = Path("C:/Windows/Fonts/msyhbd.ttc")
FALLBACK_FONT = Path("C:/Windows/Fonts/msyh.ttc")

TOP = (59, 107, 250)      # #3B6BFA
BOTTOM = (139, 92, 246)   # #8B5CF6
WHITE = (255, 255, 255)


def get_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in (FONT_PATH, FALLBACK_FONT):
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    raise SystemExit("未找到微软雅黑字体，请检查 C:/Windows/Fonts/")


def vertical_gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    base = Image.new("RGB", size)
    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(width):
            base.putpixel((x, y), color)
    return base


def draw_centered(draw: ImageDraw.ImageDraw, y: int, text: str, font: ImageFont.FreeTypeFont, fill=WHITE) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    draw.text((600 - width / 2, y), text, font=font, fill=fill)


def make_og_image() -> None:
    img = vertical_gradient((1200, 630), TOP, BOTTOM)
    draw = ImageDraw.Draw(img)
    # 品牌区（左侧 Play 三角 + 星芒 + 下载箭头，简化绘制）
    draw.rounded_rectangle((70, 70, 214, 214), radius=36, fill=(255, 255, 255, 255))
    draw.polygon([(112, 106), (176, 142), (112, 178)], fill=TOP)
    draw.line((196, 128, 196, 196), fill=TOP, width=10)
    draw.polygon([(178, 170), (196, 188), (214, 170)], outline=TOP, width=10)
    brand_font = get_font(46)
    draw.text((250, 96), "ClipNest", font=brand_font, fill=WHITE)
    draw.text((250, 158), "万能视频下载总结器", font=get_font(44), fill=WHITE)
    title_font = get_font(88)
    draw_centered(draw, 300, "粘贴链接，3 秒拿到原片", title_font)
    subtitle_font = get_font(40)
    draw_centered(draw, 448, "在线解析下载 · AI 视频总结 · 字幕与思维导图", subtitle_font)
    draw_centered(draw, 520, "YouTube · Bilibili · 抖音 · TikTok 等上千个平台", get_font(32))
    out = PUBLIC / "og-image.png"
    img.save(out, format="PNG", optimize=True)
    print(f"已生成 {out}")


def make_apple_icon() -> None:
    size = 180
    img = vertical_gradient((size, size), TOP, BOTTOM)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((18, 18, 162, 162), radius=40, fill=WHITE)
    draw.polygon([(58, 52), (118, 90), (58, 128)], fill=TOP)
    draw.line((136, 70, 136, 118), fill=TOP, width=8)
    draw.polygon([(124, 106), (136, 120), (148, 106)], outline=TOP, width=8)
    out = PUBLIC / "apple-touch-icon.png"
    img.save(out, format="PNG", optimize=True)
    print(f"已生成 {out}")


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    make_og_image()
    make_apple_icon()


if __name__ == "__main__":
    sys.exit(main())
