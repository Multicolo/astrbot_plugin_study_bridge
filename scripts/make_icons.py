#!/usr/bin/env python3
"""生成 Android 启动图标（粉色圆角方块 + 白色「学」字）。

用 Pillow，尺寸对应 mipmap-mdpi/hdpi/xhdpi/xxhdpi/xxxhdpi。
没有 Pillow 时脚本会直接说明，不会静默跳过。

用法::

    python scripts/make_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "android" / "res"
SIZES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}
PINK = (214, 51, 108, 255)
WHITE = (255, 255, 255, 255)


def find_font(size: int):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    from PIL import ImageFont

    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def main() -> int:
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("需要 Pillow：pip install pillow（或使用 DSH 运行时自带的 Python）")
        return 1

    for name, size in SIZES.items():
        # 图标画布比实际图标大一圈，保证系统裁切后仍完整
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        radius = int(size * 0.24)
        draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=PINK)
        font = find_font(int(size * 0.56))
        text = "学"
        box = draw.textbbox((0, 0), text, font=font)
        width = box[2] - box[0]
        height = box[3] - box[1]
        draw.text(
            ((size - width) / 2 - box[0], (size - height) / 2 - box[1]),
            text,
            font=font,
            fill=WHITE,
        )
        target = OUT / f"mipmap-{name}" / "ic_launcher.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="PNG")
        print(f"wrote {target.relative_to(ROOT)} ({size}x{size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
