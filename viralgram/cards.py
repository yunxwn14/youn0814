"""카드뉴스 이미지(1080x1350, 4:5) 렌더링."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .photos import Photo
from .writer import CardNews

log = logging.getLogger(__name__)

W, H = 1080, 1350
MARGIN = 96

# (배경, 강조색, 본문색) — 게시물마다 순환해 피드가 단조롭지 않게 한다.
THEMES = [
    ("#111418", "#FFD43B", "#F1F3F5"),
    ("#1B1F3B", "#FF6B6B", "#F8F9FA"),
    ("#0B3D2E", "#8CE99A", "#F8F9FA"),
    ("#FFF4E6", "#E8590C", "#212529"),
    ("#F1F3F5", "#5F3DC4", "#212529"),
]

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


def fill_photos(photos: list[Photo | None], total: int) -> list[Photo | None]:
    """페이지 수만큼 사진 목록을 맞춘다. 비어 있는 자리는 확보된 사진을 순서대로 재사용한다."""
    available = [p for p in photos if p]
    if not available:
        return [None] * total
    result, k = [], 0
    for i in range(total):
        p = photos[i] if i < len(photos) else None
        if p is None:
            p = available[k % len(available)]
            k += 1
        result.append(p)
    return result


class Renderer:
    def __init__(self, font_path: str, brand: str = "", theme_index: int = 0):
        self.font_path = find_font(font_path)
        self.brand = brand
        self.bg, self.accent, self.fg = THEMES[theme_index % len(THEMES)]

    def font(self, size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
        f = ImageFont.truetype(self.font_path, size)
        try:  # 가변 폰트(NotoSansKR[wght])면 굵기 지정
            f.set_variation_by_name(weight)
        except (OSError, ValueError, AttributeError):
            pass
        return f

    # ── 텍스트 줄바꿈 (한글은 글자 단위, 공백 우선) ─────────────
    @staticmethod
    def wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
        lines: list[str] = []
        for para in text.split("\n"):
            line = ""
            for word in para.split(" "):
                candidate = f"{line} {word}".strip()
                if draw.textlength(candidate, font=font) <= max_width:
                    line = candidate
                    continue
                if line:
                    lines.append(line)
                line = ""
                for ch in word:  # 단어 자체가 너무 길면 글자 단위로 자른다
                    if draw.textlength(line + ch, font=font) > max_width and line:
                        lines.append(line)
                        line = ""
                    line += ch
            lines.append(line)
        return lines

    def _text_block(self, draw, xy, text, font, fill, max_width, spacing=1.35) -> int:
        x, y = xy
        line_h = int(font.size * spacing)
        for line in self.wrap(draw, text, font, max_width):
            draw.text((x, y), line, font=font, fill=fill)
            y += line_h
        return y

    def _base(self, page: int, total: int, background: Image.Image | None = None,
              footer_color: str | None = None) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = background if background is not None else Image.new("RGB", (W, H), self.bg)
        draw = ImageDraw.Draw(img)
        small = self.font(30, "Medium")
        color = footer_color or self.fg
        if self.brand:
            draw.text((MARGIN, H - MARGIN), self.brand, font=small, fill=color, anchor="ls")
        draw.text((W - MARGIN, H - MARGIN), f"{page}/{total}", font=small, fill=color, anchor="rs")
        return img, draw

    def _text_height(self, draw, text, font, max_width, spacing=1.35) -> int:
        return len(self.wrap(draw, text, font, max_width)) * int(font.size * spacing)

    @staticmethod
    def _photo_background(photo: Image.Image) -> Image.Image:
        """사진을 꽉 채우고, 아래쪽으로 갈수록 어두워지는 그라데이션을 덮어 글씨가 잘 보이게 한다."""
        img = ImageOps.fit(photo, (W, H), Image.LANCZOS)
        shade = Image.new("L", (1, H))
        for y in range(H):
            t = y / H
            shade.putpixel((0, y), int(60 + 180 * max(0.0, (t - 0.25) / 0.75) ** 1.2))
        black = Image.new("RGB", (W, H), "#000000")
        return Image.composite(black, img, shade.resize((W, H)))

    # ── 페이지별 레이아웃 ─────────────────────────────────
    def cover(self, card: CardNews, region: str, total: int, photo: Photo | None = None) -> Image.Image:
        if photo:
            return self._photo_cover(card, region, total, photo)
        img, draw = self._base(1, total)
        tag_font = self.font(36)
        label = f" {region} 화제 "
        tw = draw.textlength(label, font=tag_font)
        draw.rounded_rectangle((MARGIN, 300, MARGIN + tw + 16, 360), radius=12, fill=self.accent)
        draw.text((MARGIN + 8, 330), label, font=tag_font, fill=self.bg, anchor="lm")
        y = self._text_block(draw, (MARGIN, 420), card.hook, self.font(92, "Black"), self.fg, W - 2 * MARGIN, 1.25)
        draw.rectangle((MARGIN, y + 30, MARGIN + 120, y + 42), fill=self.accent)
        self._text_block(draw, (MARGIN, y + 80), card.subtitle, self.font(44, "Medium"), self.fg, W - 2 * MARGIN)
        draw.text((W - MARGIN, H - MARGIN - 70), "옆으로 넘겨보세요 →", font=self.font(34, "Medium"),
                  fill=self.accent, anchor="rs")
        return img

    def _photo_cover(self, card: CardNews, region: str, total: int, photo: Photo) -> Image.Image:
        white = "#FFFFFF"
        img, draw = self._base(1, total, self._photo_background(photo.image), white)
        width = W - 2 * MARGIN
        hook_font, sub_font = self.font(88, "Black"), self.font(42, "Medium")
        block = (60 + 40 + self._text_height(draw, card.hook, hook_font, width, 1.25)
                 + 70 + self._text_height(draw, card.subtitle, sub_font, width))
        y = H - MARGIN - 130 - block
        tag_font = self.font(36)
        label = f" {region} 화제 "
        tw = draw.textlength(label, font=tag_font)
        draw.rounded_rectangle((MARGIN, y, MARGIN + tw + 16, y + 60), radius=12, fill=self.accent)
        draw.text((MARGIN + 8, y + 30), label, font=tag_font, fill="#111111", anchor="lm")
        y = self._text_block(draw, (MARGIN, y + 100), card.hook, hook_font, white, width, 1.25)
        draw.rectangle((MARGIN, y + 20, MARGIN + 120, y + 32), fill=self.accent)
        self._text_block(draw, (MARGIN, y + 70), card.subtitle, sub_font, white, width)
        draw.text((W - MARGIN, H - MARGIN - 70), "옆으로 넘겨보세요 →", font=self.font(34, "Medium"),
                  fill=self.accent, anchor="rs")
        return img

    def slide(self, heading: str, body: str, page: int, total: int, photo: Photo | None = None) -> Image.Image:
        if photo:
            return self._photo_slide(heading, body, page, total, photo)
        img, draw = self._base(page, total)
        draw.text((MARGIN, 220), f"{page - 1:02d}", font=self.font(120, "Black"), fill=self.accent)
        y = self._text_block(draw, (MARGIN, 400), heading, self.font(70, "Black"), self.fg, W - 2 * MARGIN, 1.25)
        self._text_block(draw, (MARGIN, y + 60), body, self.font(50, "Regular"), self.fg, W - 2 * MARGIN, 1.6)
        return img

    def _photo_slide(self, heading: str, body: str, page: int, total: int, photo: Photo) -> Image.Image:
        """위쪽 절반은 사진, 아래쪽은 글."""
        img, draw = self._base(page, total)
        img.paste(ImageOps.fit(photo.image, (W, 600), Image.LANCZOS), (0, 0))
        num_font = self.font(48, "Black")
        label = f"{page - 1:02d}"
        box_w = draw.textlength(label, font=num_font) + 48
        draw.rectangle((MARGIN, 600 - 40, MARGIN + box_w, 600 + 40), fill=self.accent)
        draw.text((MARGIN + box_w / 2, 600), label, font=num_font, fill=self.bg, anchor="mm")
        y = self._text_block(draw, (MARGIN, 690), heading, self.font(64, "Black"), self.fg, W - 2 * MARGIN, 1.25)
        self._text_block(draw, (MARGIN, y + 36), body, self.font(44, "Regular"), self.fg, W - 2 * MARGIN, 1.55)
        return img

    def closing(self, card: CardNews, total: int, photo: Photo | None = None) -> Image.Image:
        if photo:
            return self._photo_closing(card, total, photo)
        img, draw = self._base(total, total)
        y = self._text_block(draw, (MARGIN, 420), card.closing, self.font(76, "Black"), self.accent, W - 2 * MARGIN, 1.3)
        self._text_block(draw, (MARGIN, y + 80), "댓글로 여러분 생각을 알려주세요\n저장하고 친구에게도 공유하기",
                         self.font(44, "Medium"), self.fg, W - 2 * MARGIN, 1.7)
        self._text_block(draw, (MARGIN, H - 300), card.source_credit, self.font(32, "Regular"), self.fg, W - 2 * MARGIN)
        return img

    def _photo_closing(self, card: CardNews, total: int, photo: Photo) -> Image.Image:
        white = "#FFFFFF"
        img, draw = self._base(total, total, self._photo_background(photo.image), white)
        width = W - 2 * MARGIN
        q_font, cta_font = self.font(76, "Black"), self.font(42, "Medium")
        cta = "댓글로 여러분 생각 남겨주세요\n이거 본 친구 태그하기"
        block = self._text_height(draw, card.closing, q_font, width, 1.3) + 70 + self._text_height(draw, cta, cta_font, width, 1.6)
        y = H - MARGIN - 190 - block
        y = self._text_block(draw, (MARGIN, y), card.closing, q_font, self.accent, width, 1.3)
        self._text_block(draw, (MARGIN, y + 70), cta, cta_font, white, width, 1.6)
        draw.text((MARGIN, H - MARGIN - 80), card.source_credit, font=self.font(30, "Regular"), fill=white, anchor="ls")
        return img

    def render(self, card: CardNews, region: str, out_dir: Path, photos: list[Photo | None] | None = None) -> list[Path]:
        """photos 는 페이지 순서(표지, 본문..., 마지막 장). 빈 자리는 확보된 사진을 돌려 써서 모든 페이지에 사진을 넣는다."""
        out_dir.mkdir(parents=True, exist_ok=True)
        total = len(card.slides) + 2
        page_photos = fill_photos(photos or [], total)
        pages = [self.cover(card, region, total, page_photos[0])]
        pages += [self.slide(s.heading, s.body, i + 2, total, page_photos[i + 1]) for i, s in enumerate(card.slides)]
        pages.append(self.closing(card, total, page_photos[-1]))
        paths = []
        for i, page in enumerate(pages, 1):
            path = out_dir / f"{i:02d}.jpg"
            page.save(path, "JPEG", quality=92)
            paths.append(path)
        log.info("카드 %d장 생성: %s", len(paths), out_dir)
        return paths
