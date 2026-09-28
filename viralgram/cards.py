"""썸네일형 게시물 이미지(1080x1350, 4:5) 렌더링.

1장: 사진 전면 + 아래쪽 어두운 그라데이션 + @계정명 + 굵은 제목 2줄
2장: 글씨 없는 사진 (있을 때만)
"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .photos import Photo
from .writer import CardNews

log = logging.getLogger(__name__)

W, H = 1080, 1350
MARGIN_X = 90
BOTTOM = 190  # 제목 마지막 줄 아래 여백

FONT_CANDIDATES = [
    "fonts/NotoSansKR.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "C:/Windows/Fonts/malgunbd.ttf",
]


def find_font(preferred: str = "") -> str:
    for path in [preferred, *FONT_CANDIDATES]:
        if path and Path(path).exists():
            return path
    raise FileNotFoundError(
        "한국어 폰트를 찾을 수 없습니다. README 의 폰트 설치 안내를 참고해 FONT_PATH 를 지정하세요."
    )


class Renderer:
    def __init__(self, font_path: str, brand: str = ""):
        self.font_path = find_font(font_path)
        self.brand = brand if not brand or brand.startswith("@") else f"@{brand}"

    def font(self, size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
        f = ImageFont.truetype(self.font_path, size)
        try:  # 가변 폰트(NotoSansKR[wght])면 굵기 지정
            f.set_variation_by_name(weight)
        except (OSError, ValueError, AttributeError):
            pass
        return f

    @staticmethod
    def _shade(img: Image.Image) -> Image.Image:
        """아래 45% 구간을 점점 어둡게 덮어 글씨가 잘 보이게 한다."""
        mask = Image.new("L", (1, H))
        start = int(H * 0.45)
        for y in range(H):
            t = max(0.0, (y - start) / (H - start))
            mask.putpixel((0, y), int(235 * min(1.0, t * 1.4) ** 1.3))
        return Image.composite(Image.new("RGB", (W, H), "#000000"), img, mask.resize((W, H)))

    def _headline_font(self, draw: ImageDraw.ImageDraw, lines: list[str]) -> ImageFont.FreeTypeFont:
        """가장 긴 줄이 가로 폭에 들어가도록 글자 크기를 줄인다 (최대 116px)."""
        size = 116
        while size > 56:
            f = self.font(size, "Black")
            if max(draw.textlength(line, font=f) for line in lines) <= W - 2 * MARGIN_X:
                return f
            size -= 4
        return self.font(size, "Black")

    def thumbnail(self, headline: str, photo: Photo | None) -> Image.Image:
        base = ImageOps.fit(photo.image, (W, H), Image.LANCZOS) if photo else Image.new("RGB", (W, H), "#222222")
        img = self._shade(base)
        draw = ImageDraw.Draw(img)
        lines = [line.strip() for line in headline.split("\n") if line.strip()][:3] or [headline]
        font = self._headline_font(draw, lines)
        line_h = int(font.size * 1.22)
        y = H - BOTTOM - line_h * len(lines)
        if self.brand:
            draw.text((MARGIN_X, y - 30), self.brand, font=self.font(46, "Bold"), fill="#FFFFFF", anchor="ls")
        for line in lines:
            draw.text((MARGIN_X, y), line, font=font, fill="#FFFFFF", stroke_width=1, stroke_fill="#000000")
            y += line_h
        return img

    @staticmethod
    def plain(photo: Photo) -> Image.Image:
        return ImageOps.fit(photo.image, (W, H), Image.LANCZOS)

    def render(self, card: CardNews, out_dir: Path, photos: list[Photo | None] | None = None) -> list[Path]:
        """photos[0] 은 썸네일 배경, photos[1] 이 있으면 글씨 없는 2번째 장으로 붙인다."""
        out_dir.mkdir(parents=True, exist_ok=True)
        found = [p for p in (photos or []) if p]
        pages = [self.thumbnail(card.headline, found[0] if found else None)]
        if len(found) > 1:
            pages.append(self.plain(found[1]))
        paths = []
        for i, page in enumerate(pages, 1):
            path = out_dir / f"{i:02d}.jpg"
            page.save(path, "JPEG", quality=92)
            paths.append(path)
        log.info("이미지 %d장 생성: %s", len(paths), out_dir)
        return paths
