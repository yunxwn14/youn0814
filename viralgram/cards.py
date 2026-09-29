"""썸네일형 게시물 이미지(1080x1350, 4:5) 렌더링.

1장: 레이아웃에 맞춘 사진 구성 + 아래쪽 어두운 그라데이션 + @계정명 + 굵은 제목 2줄
  - single: 사진 1장 전면
  - split: 두 이미지 좌우로 나란히
  - inset: 메인 사진 + 왼쪽 위 원형 작은 사진
  - compare: 위아래 비교 + 각 라벨 (예: 1799년 / 2026년)
2장~: 글씨 없는 사진 (있을 때만)
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

    # ── 배경 구성 ─────────────────────────────────────────
    def _ai_tag(self, img: Image.Image, box: tuple[int, int, int, int]) -> None:
        """AI 생성 이미지 영역 오른쪽 위에 작은 표시."""
        draw = ImageDraw.Draw(img)
        f = self.font(26, "Bold")
        text = "AI 생성 이미지"
        tw = draw.textlength(text, font=f)
        x1, y0 = box[2] - 24, box[1] + 24
        draw.rounded_rectangle((x1 - tw - 24, y0, x1, y0 + 44), radius=10, fill=(0, 0, 0))
        draw.text((x1 - 12, y0 + 22), text, font=f, fill="#FFFFFF", anchor="rm")

    def _label(self, img: Image.Image, text: str, center_x: int, top: int) -> None:
        """compare 레이아웃의 검은 박스 라벨 (예: '1799년')."""
        if not text.strip():
            return
        draw = ImageDraw.Draw(img)
        f = self.font(78, "Black")
        tw = draw.textlength(text, font=f)
        draw.rectangle((center_x - tw / 2 - 20, top, center_x + tw / 2 + 20, top + 104), fill="#000000")
        draw.text((center_x, top + 52), text, font=f, fill="#FFFFFF", anchor="mm")

    def compose(self, layout: str, a: Photo | None, b: Photo | None = None,
                label_a: str = "", label_b: str = "") -> Image.Image:
        if a is None:
            return Image.new("RGB", (W, H), "#222222")
        if b is None or layout == "single":
            img = ImageOps.fit(a.image, (W, H), Image.LANCZOS)
            if a.ai:
                self._ai_tag(img, (0, 0, W, H))
            return img
        img = Image.new("RGB", (W, H), "#FFFFFF")
        if layout == "split":
            half = W // 2
            img.paste(ImageOps.fit(a.image, (half - 3, H), Image.LANCZOS), (0, 0))
            img.paste(ImageOps.fit(b.image, (W - half - 3, H), Image.LANCZOS), (half + 3, 0))
            if a.ai:
                self._ai_tag(img, (0, 0, half, H))
            if b.ai:
                self._ai_tag(img, (half, 0, W, H))
        elif layout == "compare":
            half = H // 2
            img.paste(ImageOps.fit(a.image, (W, half - 3), Image.LANCZOS), (0, 0))
            img.paste(ImageOps.fit(b.image, (W, H - half - 3), Image.LANCZOS), (0, half + 3))
            self._label(img, label_a, W // 2, 90)
            self._label(img, label_b, W // 2, half + 60)
            if a.ai:
                self._ai_tag(img, (0, 0, W, half))
            if b.ai:
                self._ai_tag(img, (0, half, W, H))
        else:  # inset
            img = ImageOps.fit(a.image, (W, H), Image.LANCZOS)
            d, x, y, border = 380, 50, 70, 10
            circle = ImageOps.fit(b.image, (d, d), Image.LANCZOS)
            mask = Image.new("L", (d, d), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, d, d), fill=255)
            ImageDraw.Draw(img).ellipse((x - border, y - border, x + d + border, y + d + border), fill="#FFFFFF")
            img.paste(circle, (x, y), mask)
            if a.ai or b.ai:
                self._ai_tag(img, (0, 0, W, H))
        return img

    # ── 페이지 ────────────────────────────────────────────
    def thumbnail(self, headline: str, background: Image.Image) -> Image.Image:
        img = self._shade(background)
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

    def plain(self, photo: Photo) -> Image.Image:
        img = ImageOps.fit(photo.image, (W, H), Image.LANCZOS)
        if photo.ai:
            self._ai_tag(img, (0, 0, W, H))
        return img

    def render(self, card: CardNews, out_dir: Path, a: Photo | None, b: Photo | None = None,
               extras: list[Photo | None] | None = None) -> list[Path]:
        """1장: 레이아웃대로 a·b 를 배치한 썸네일. 이후: 글씨 없는 사진들 (b, extras 중 썸네일에 안 쓴 것)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        layout = card.layout if b is not None else "single"
        label_a = card.image_a.label if card.image_a else ""
        label_b = card.image_b.label if card.image_b else ""
        pages = [self.thumbnail(card.headline, self.compose(layout, a, b, label_a, label_b))]
        for photo in [p for p in (extras or []) if p][:1]:
            pages.append(self.plain(photo))
        paths = []
        for i, page in enumerate(pages, 1):
            path = out_dir / f"{i:02d}.jpg"
            page.save(path, "JPEG", quality=92)
            paths.append(path)
        log.info("이미지 %d장 생성 (%s): %s", len(paths), layout, out_dir)
        return paths
