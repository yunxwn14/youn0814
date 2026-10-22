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
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat
from PIL import ImageFont

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


def fit_whole(img: Image.Image, size: tuple[int, int], anchor: float = 0.5) -> Image.Image:
    """사진을 자르지 않고 전체가 보이게 맞춘다. 남는 부분은 같은 사진을 흐리게 깔아 채운다.
    anchor: 남는 세로 공간에서 사진이 놓일 위치 (0=맨 위, 0.5=가운데). 제목이 들어갈 아래쪽을 비워 두려면 작게."""
    w, h = size
    img = img.convert("RGB")
    bg = ImageOps.fit(img, (w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(30))
    bg = ImageEnhance.Brightness(bg).enhance(0.6)
    fg = ImageOps.contain(img, (w, h), Image.LANCZOS)
    bg.paste(fg, ((w - fg.width) // 2, int((h - fg.height) * anchor)))
    return bg


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

    def display(self, size: int) -> ImageFont.FreeTypeFont:
        return self.font(size, "ExtraBold")

    @staticmethod
    def _shade(img: Image.Image) -> Image.Image:
        """아래 45% 구간을 점점 어둡게 덮어 글씨가 잘 보이게 한다."""
        mask = Image.new("L", (1, H))
        start = int(H * 0.45)
        for y in range(H):
            t = max(0.0, (y - start) / (H - start))
            mask.putpixel((0, y), int(235 * min(1.0, t * 1.4) ** 1.3))
        return Image.composite(Image.new("RGB", (W, H), "#000000"), img, mask.resize((W, H)))

    def _clean_size(self, draw: ImageDraw.ImageDraw, lines: list[str]) -> int:
        plain = [re.sub(r"'", "", ln) for ln in lines]
        size = 108
        while size > 56:
            f = self.font(size, "Black")
            if max(draw.textlength(ln, font=f) for ln in plain) <= W - 2 * MARGIN_X:
                break
            size -= 4
        return size

    def _headline_font(self, draw: ImageDraw.ImageDraw, lines: list[str], bold: bool = False) -> ImageFont.FreeTypeFont:
        """가장 긴 줄이 가로 폭에 들어가도록 글자 크기를 줄인다 (최대 116px, 디스플레이 서체는 132px)."""
        size = 132 if bold else 116
        while size > 56:
            f = self.display(size) if bold else self.font(size, "Black")
            if max(draw.textlength(line, font=f) for line in lines) <= W - 2 * MARGIN_X:
                return f
            size -= 4
        return self.display(size) if bold else self.font(size, "Black")

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
            img = fit_whole(a.image, (W, H), anchor=0.35)
            if a.ai:
                self._ai_tag(img, (0, 0, W, H))
            return img
        img = Image.new("RGB", (W, H), "#FFFFFF")
        landscape = a.image.width > a.image.height and b.image.width > b.image.height
        if layout == "split" and landscape:
            # 가로 사진 두 장을 좁은 반쪽씩에 넣으면 너무 작아지므로 위아래로 쌓는다 (라벨 없이)
            layout, label_a, label_b = "compare", "", ""
        if layout == "split":
            half = W // 2
            img.paste(fit_whole(a.image, (half - 3, H), anchor=0.35), (0, 0))
            img.paste(fit_whole(b.image, (W - half - 3, H), anchor=0.35), (half + 3, 0))
            if a.ai:
                self._ai_tag(img, (0, 0, half, H))
            if b.ai:
                self._ai_tag(img, (half, 0, W, H))
        elif layout == "compare":
            half = H // 2
            img.paste(fit_whole(a.image, (W, half - 3)), (0, 0))
            img.paste(fit_whole(b.image, (W, H - half - 3)), (0, half + 3))
            self._label(img, label_a, W // 2, 90)
            self._label(img, label_b, W // 2, half + 60)
            if a.ai:
                self._ai_tag(img, (0, 0, W, half))
            if b.ai:
                self._ai_tag(img, (0, half, W, H))
        else:  # inset
            img = fit_whole(a.image, (W, H), anchor=0.35)
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
    def _clean_headline(self, img: Image.Image, lines: list[str], y: int, size: int) -> None:
        """정치 모드 제목: 흰색 한 가지, 서체 한 가지. 핵심어(작은따옴표)는 굵기 대비로만 강조하고,
        가독성은 외곽선 대신 부드러운 그림자로 확보한다. 큰 제목이라 행간은 촘촘하게(1.14)."""
        regular, heavy = self.font(size, "Medium"), self.font(size, "Black")
        line_h = int(size * 1.14)
        shadow = Image.new("L", img.size, 0)
        sd, d = ImageDraw.Draw(shadow), ImageDraw.Draw(img)
        runs = []
        for i, line in enumerate(lines):
            x, ly = MARGIN_X, y + i * line_h
            for seg in re.split(r"('[^']*')", line):
                if not seg:
                    continue
                hot = seg.startswith("'") and seg.endswith("'") and len(seg) > 2
                seg = seg.strip("'") if hot else seg.replace("'", "")
                f = heavy if hot else regular
                runs.append(((x, ly), seg, f))
                w = d.textlength(seg, font=f)
                x += w
        for xy, seg, f in runs:
            sd.text((xy[0] + 2, xy[1] + 4), seg, font=f, fill=255)
        shadow = shadow.filter(ImageFilter.GaussianBlur(9)).point(lambda v: int(v * 0.85))
        img.paste(Image.new("RGB", img.size, "#000000"), (0, 0), shadow)
        d = ImageDraw.Draw(img)
        for xy, seg, f in runs:
            d.text(xy, seg, font=f, fill="#FFFFFF")

    def _tag(self, img: Image.Image, text: str) -> None:
        """왼쪽 위 코너 라벨 (예: '쉬운 해설'): 흰 알약 + 검정 글씨."""
        draw = ImageDraw.Draw(img)
        f = self.font(38, "Bold")
        tw = draw.textlength(text, font=f)
        draw.rounded_rectangle((MARGIN_X - 26, 62, MARGIN_X + tw + 26, 132), radius=35, fill="#FFFFFF")
        draw.text((MARGIN_X, 97), text, font=f, fill="#111111", anchor="lm")

    def thumbnail(self, headline: str, background: Image.Image, tag: str = "", accent: bool = False) -> Image.Image:
        img = self._shade(background)
        draw = ImageDraw.Draw(img)
        lines = [line.strip() for line in headline.split("\n") if line.strip()][:3] or [headline]
        if accent:
            size = self._clean_size(draw, lines)
            y = H - BOTTOM - int(size * 1.14) * len(lines)
            if self.brand:
                draw.text((MARGIN_X, y - 34), self.brand, font=self.font(40, "Medium"), fill="#FFFFFF", anchor="ls")
            self._clean_headline(img, lines, y, size)
        else:
            font = self._headline_font(draw, lines)
            line_h = int(font.size * 1.22)
            y = H - BOTTOM - line_h * len(lines)
            if self.brand:
                draw.text((MARGIN_X, y - 30), self.brand, font=self.font(46, "Bold"), fill="#FFFFFF", anchor="ls")
            for line in lines:
                draw.text((MARGIN_X, y), line, font=font, fill="#FFFFFF", stroke_width=1, stroke_fill="#000000")
                y += line_h
        if tag:
            self._tag(img, tag)
        return img

    def _wrap(self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
        """어절 단위로 줄바꿈 (한 어절이 폭보다 길면 글자 단위로)."""
        lines, cur = [], ""
        for word in text.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= width:
                cur = trial
                continue
            if cur:
                lines.append(cur)
                cur = ""
            for ch in word:
                if draw.textlength(cur + ch, font=font) > width and cur:
                    lines.append(cur)
                    cur = ch
                else:
                    cur += ch
        return lines + ([cur] if cur else [])

    def plain(self, photo: Photo, quip: str = "") -> Image.Image:
        """글씨 없는 사진 페이지. 가로 사진이라 아래 여백이 크면 탐정냥 한마디를 그 자리에 넣는다."""
        img = fit_whole(photo.image, (W, H), anchor=0.3)
        if photo.ai:
            self._ai_tag(img, (0, 0, W, H))
        shown_h = min(H, round(photo.image.height * W / photo.image.width)) if photo.image.width else H
        free_top = int((H - shown_h) * 0.3) + shown_h  # 사진 아래 끝
        if quip.strip() and H - free_top > 330:
            draw = ImageDraw.Draw(img)
            font = self.font(52, "Black")
            lines = self._wrap(draw, quip, font, W - 2 * MARGIN_X)[:3]
            y = free_top + (H - free_top - 60 - 74 * len(lines)) // 2 + 60
            draw.text((MARGIN_X, y - 56), "🐾 탐정냥 한마디".replace("🐾 ", ""), font=self.font(36, "Bold"), fill="#FFFFFF")
            for line in lines:
                draw.text((MARGIN_X, y + 20), line, font=font, fill="#FFFFFF", stroke_width=1, stroke_fill="#000000")
                y += 74
        return img

    def explain_page(self, title: str, text: str, index: int, total: int) -> Image.Image:
        """쉬운 해설 카드: 어두운 배경에 소제목 + 본문 + 진행 표시."""
        img = Image.new("RGB", (W, H), "#14161F")
        draw = ImageDraw.Draw(img)
        draw.text((MARGIN_X, 150), f"{index} / {total}", font=self.font(44, "Bold"), fill="#B9BDC9", anchor="ls")
        tf = self.font(88, "ExtraBold")
        y = 290
        for line in self._wrap(draw, title, tf, W - 2 * MARGIN_X)[:2]:
            draw.text((MARGIN_X, y), line, font=tf, fill="#FFFFFF")
            y += 112
        bf = self.font(58, "Bold")
        y += 90
        for line in self._wrap(draw, text, bf, W - 2 * MARGIN_X)[:9]:
            draw.text((MARGIN_X, y), line, font=bf, fill="#E8E8EE")
            y += 88
        if self.brand:
            draw.text((MARGIN_X, H - 90), self.brand, font=self.font(40, "Bold"), fill="#8A8FA3", anchor="ls")
        return img

    def follow_card(self, background: Image.Image | None = None,
                    lines: tuple[str, str, str, str] = ("다음 사건도", "놓치지 마세요", "팔로우하고 매일 새로운", "화제 이슈 소식 받아보기")) -> Image.Image:
        """마지막 장: 팔로우 부탁. 배경은 썸네일 사진을 흐리게 깔거나 단색."""
        if background is not None and ImageStat.Stat(ImageOps.grayscale(background.resize((64, 64)))).stddev[0] > 25:
            img = ImageEnhance.Brightness(
                ImageOps.fit(background.convert("RGB"), (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(36))
            ).enhance(0.35)
        else:
            img = Image.new("RGB", (W, H), "#1B1B1F")
        draw = ImageDraw.Draw(img)
        cx = W // 2
        draw.text((cx, 470), lines[0], font=self.font(104, "ExtraBold"), fill="#FFFFFF", anchor="mm")
        draw.text((cx, 600), lines[1], font=self.font(104, "ExtraBold"), fill="#FFFFFF", anchor="mm")
        draw.text((cx, 790), lines[2], font=self.font(54, "Bold"), fill="#FFFFFF", anchor="mm")
        draw.text((cx, 870), lines[3], font=self.font(54, "Bold"), fill="#FFFFFF", anchor="mm")
        if self.brand:
            f = self.font(60, "Black")
            tw = draw.textlength(self.brand, font=f)
            draw.rounded_rectangle((cx - tw / 2 - 40, 990, cx + tw / 2 + 40, 1100), radius=55, fill="#FFFFFF")
            draw.text((cx, 1045), self.brand, font=f, fill="#111111", anchor="mm")
        draw.text((cx, 1190), "저장 · 공유도 큰 힘이 됩니다", font=self.font(40, "Bold"),
                  fill="#CCCCCC", anchor="mm")
        return img

    def render(self, card: CardNews, out_dir: Path, a: Photo | None, b: Photo | None = None,
               extras: list[Photo | None] | None = None, mode: str = "") -> list[Path]:
        """1장: 레이아웃대로 a·b 를 배치한 썸네일. 이후: 글씨 없는 사진들 (b, extras 중 썸네일에 안 쓴 것)."""
        out_dir.mkdir(parents=True, exist_ok=True)
        layout = card.layout if b is not None else "single"
        label_a = card.image_a.label if card.image_a else ""
        label_b = card.image_b.label if card.image_b else ""
        political = mode in {"satire", "explainer", "politics"}
        tag = {"explainer": "쉬운 해설"}.get(mode, "")  # 풍자·정치 뉴스는 라벨 없이 제목만
        if political and a is not None and (a.ai or not a.credit):
            # 정치 모드: AI 장면(또는 단색 표지)은 잘라서 화면을 꽉 채운다. 기사 사진은 자르지 않고 전체를 보여준다
            bg = ImageOps.fit(a.image.convert("RGB"), (W, H), Image.LANCZOS, centering=(0.5, 0.35))
            if a.ai:
                self._ai_tag(bg, (0, 0, W, H))
        else:
            bg = self.compose(layout, a, b, label_a, label_b)
        pages = [self.thumbnail(card.headline, bg, tag, accent=political)]
        if mode == "explainer" and card.steps:
            steps = card.steps[:4]
            pages += [self.explain_page(s.title, s.text, i, len(steps)) for i, s in enumerate(steps, 1)]
        else:
            for photo in [p for p in (extras or []) if p][:1]:
                pages.append(self.plain(photo, card.quip))
        follow = {"satire": ("정치, 웃기게", "읽어드려요", "팔로우하고 매일 새로운", "정치 밈·해설 받아보기"),
                  "explainer": ("정치, 쉽게", "읽어드려요", "팔로우하고 매주 일요일", "쉬운 정치 해설 받아보기"),
                  "politics": ("오늘의 정치", "한눈에", "팔로우하고 매일 새로운", "정치 이슈 받아보기")}.get(mode)
        pages.append(self.follow_card(a.image if a else None, follow) if follow else self.follow_card(a.image if a else None))
        paths = []
        for i, page in enumerate(pages, 1):
            path = out_dir / f"{i:02d}.jpg"
            page.save(path, "JPEG", quality=92)
            paths.append(path)
        log.info("이미지 %d장 생성 (%s): %s", len(paths), layout, out_dir)
        return paths
