"""
Generate a professional, multi-size Windows icon (.ico) and favicon for Shinri Reviews Ranker.
DRO theme: Neon Gold Star with Cyberpunk/Danganronpa Dark Obsidian & Violet accents.
"""

from PIL import Image, ImageDraw, ImageFilter
import math
import os
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def create_master_icon(size=512):
    # 512x512 master image with supersampling for crisp scaling
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    center = size / 2
    r_outer = size * 0.46

    # 1. Outer Glow
    for i in range(12):
        glow_r = r_outer + (12 - i) * 3
        alpha = int(8 + i * 4)
        draw.ellipse(
            [center - glow_r, center - glow_r, center + glow_r, center + glow_r],
            fill=(124, 58, 237, alpha),  # Violet glow
        )

    # 2. Main Circle Body (Dark Obsidian Gradient)
    circle_img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    c_draw = ImageDraw.Draw(circle_img)
    c_draw.ellipse(
        [center - r_outer, center - r_outer, center + r_outer, center + r_outer],
        fill=(14, 14, 28, 255),
    )
    img = Image.alpha_composite(img, circle_img)
    draw = ImageDraw.Draw(img)

    # 3. Double Gold Border
    draw.ellipse(
        [center - r_outer, center - r_outer, center + r_outer, center + r_outer],
        outline=(245, 158, 11, 255),
        width=int(size * 0.035),
    )
    r_inner_border = r_outer * 0.92
    draw.ellipse(
        [center - r_inner_border, center - r_inner_border, center + r_inner_border, center + r_inner_border],
        outline=(251, 191, 36, 160),
        width=int(size * 0.015),
    )

    # 4. Draw Central 5-pointed Golden Star (Shinri Star)
    points = []
    outer_star_r = r_outer * 0.65
    inner_star_r = r_outer * 0.28
    angle_offset = -math.pi / 2  # Point straight up

    for i in range(10):
        r = outer_star_r if i % 2 == 0 else inner_star_r
        angle = angle_offset + i * math.pi / 5
        x = center + r * math.cos(angle)
        y = center + r * math.sin(angle)
        points.append((x, y))

    # Star Shadow / Glow
    star_glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sg_draw = ImageDraw.Draw(star_glow)
    sg_draw.polygon(points, fill=(245, 158, 11, 180))
    star_glow = star_glow.filter(ImageFilter.GaussianBlur(radius=8))
    img = Image.alpha_composite(img, star_glow)
    draw = ImageDraw.Draw(img)

    # Star Body with shading (split rays)
    for i in range(5):
        p_center = (center, center)
        p_outer = points[i * 2]
        p_inner_right = points[(i * 2 + 1) % 10]
        p_inner_left = points[(i * 2 - 1) % 10]

        # Light facet
        draw.polygon([p_center, p_outer, p_inner_right], fill=(253, 224, 71, 255))
        # Dark facet (for 3D bevel effect)
        draw.polygon([p_center, p_outer, p_inner_left], fill=(217, 119, 6, 255))

    # 5. Core Crystal (Cyan/Aqua DRO highlight)
    core_r = size * 0.06
    draw.ellipse(
        [center - core_r, center - core_r, center + core_r, center + core_r],
        fill=(56, 189, 248, 255),
        outline=(255, 255, 255, 220),
        width=int(size * 0.01),
    )

    return img

def main():
    print("Генерация мастер-изображения иконки приложения...")
    master = create_master_icon(512)

    # Standard Windows icon sizes
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

    ico_path = os.path.abspath("app_icon.ico")
    favicon_path = os.path.abspath(os.path.join("shinri_ranker", "static", "favicon.ico"))
    png_icon_path = os.path.abspath(os.path.join("shinri_ranker", "static", "app_icon.png"))

    # Save PNG preview
    master.resize((256, 256), Image.Resampling.LANCZOS).save(png_icon_path, format="PNG")
    print(f"✓ Сохранена иконка PNG: {png_icon_path}")

    # Save multi-size .ico files
    master.save(ico_path, format="ICO", sizes=sizes)
    print(f"✓ Создан Windows App Icon: {ico_path} (размеры: {', '.join(f'{w}x{h}' for w, h in sizes)})")

    master.save(favicon_path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    print(f"✓ Создан Web Favicon: {favicon_path}")

if __name__ == "__main__":
    main()
