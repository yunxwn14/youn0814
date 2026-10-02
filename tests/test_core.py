from pathlib import Path

from PIL import Image

from viralgram.cards import Renderer
from viralgram.photos import Photo
from viralgram.history import History
from viralgram.sources import parse_feed
from viralgram.writer import CardNews, ImageSpec, build_caption, validate_card

GOOGLE_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Google 뉴스</title>
<item><title>고양이가 편의점 점장이 됐다 - 연합뉴스</title><link>https://news.google.com/a</link>
<description>&lt;a href="x"&gt;고양이&lt;/a&gt; 점장 이야기</description><source url="https://yna.co.kr">연합뉴스</source></item>
<item><title>고양이가 편의점 점장이 됐다 - 연합뉴스</title><link>https://news.google.com/b</link></item>
</channel></rss>"""


def sample_card() -> CardNews:
    return CardNews(
        headline="실수로 어항 깨자, 싱크대에\n물받아 금붕어 살려준 도둑들",
        body="영국의 한 가정집에 침입한 절도범들이 깨진 어항 속 금붕어를 싱크대에 옮겨 살려두고 달아났습니다.",
        quip="도둑도 금붕어 앞에선 약해진다옹",
        hashtags=["#금붕어", "도둑", "#금붕어", "#해외 이슈"],
        source_credit="출처: 연합뉴스",
        article_url="",
        layout="single",
        image_a=ImageSpec(source="stock", stock_query="goldfish", ai_prompt="", label=""),
        image_b=None,
    )


def test_photo_queries_follow_page_order():
    assert sample_card().photo_queries == ["goldfish"]
    card = sample_card().model_copy(update={"layout": "split", "image_b": ImageSpec(
        source="ai", stock_query="thief", ai_prompt="a burglar", label="")})
    assert card.photo_queries == ["goldfish", "thief"]


def test_parse_feed_splits_source_and_cleans_html():
    stories = parse_feed("국내", GOOGLE_RSS)
    assert stories[0].title == "고양이가 편의점 점장이 됐다"
    assert stories[0].source == "연합뉴스"
    assert "<a" not in stories[0].summary
    assert stories[0].id == stories[1].id  # 같은 제목 → 같은 id (중복 제거용)


def test_history_roundtrip(tmp_path: Path):
    h = History(tmp_path / "posted.json")
    h.add("abc", "제목", "https://x", "123")
    h.save()
    assert History(tmp_path / "posted.json").ids == {"abc"}


def test_caption_dedupes_hashtags_and_limits_length():
    caption = build_caption(sample_card())
    assert caption.startswith("[실수로 어항 깨자, 싱크대에 물받아 금붕어 살려준 도둑들]")
    assert caption.count("#금붕어") == 1
    assert "#해외이슈" in caption and "#도둑" in caption
    assert caption.count("출처: 연합뉴스") == 1
    assert len(caption) <= 2200


def test_render_cards(tmp_path: Path):
    paths = Renderer("fonts/NotoSansKR.ttf", "viral_story").render(sample_card(), tmp_path, None)
    assert len(paths) == 2
    assert Image.open(paths[0]).size == (1080, 1350)


def test_instagram_host_detection():
    from viralgram.instagram import Instagram
    assert Instagram.host_for("IGAAxxxx") == "graph.instagram.com"
    assert Instagram.host_for("EAAGxxxx") == "graph.facebook.com"


def fake_photo(seed: int) -> Photo:
    img = Image.radial_gradient("L").resize((1200, 900)).convert("RGB")
    return Photo(Image.merge("RGB", [c.point(lambda v, k=k: (v + seed * 60 * (k + 1)) % 256) for k, c in enumerate(img.split())]), f"Tester{seed} / Pexels")


def test_render_cards_with_photos(tmp_path: Path):
    paths = Renderer("fonts/NotoSansKR.ttf", "@viral_story").render(
        sample_card(), tmp_path, fake_photo(1), None, [None, fake_photo(2)])
    assert len(paths) == 3  # 썸네일 + 글씨 없는 사진 + 팔로우 안내
    assert all(Image.open(p).size == (1080, 1350) for p in paths)


def test_caption_includes_photo_credits():
    caption = build_caption(sample_card(), ["A / Pexels", "A / Pexels", "B / Pexels"])
    assert "사진: A / Pexels, B / Pexels" in caption


def test_validate_card_rejects_broken_output():
    assert validate_card(sample_card()) == ""
    assert "한글" in validate_card(sample_card().model_copy(update={"headline": '"\U0001f608\ufe0f\U0001f609"'}))
    assert "문자" in validate_card(sample_card().model_copy(update={"headline": "성묘 갔더니 할머니 산소 앞\n골프 연습 \U0001f3cc"}))
    empty = ImageSpec(source="stock", stock_query=" ", ai_prompt="", label="")
    assert "검색어" in validate_card(sample_card().model_copy(update={"image_a": empty}))
    article = ImageSpec(source="article", stock_query="", ai_prompt="", label="")
    assert validate_card(sample_card().model_copy(update={"image_a": article})) == ""


def test_validate_card_rejects_vague_headline():
    card = sample_card().model_copy(update={"headline": "1500만원 골드바 내밀며\n며느리에게 '이것' 양보 종용"})
    assert "숨김" in validate_card(card)


def test_caption_signoff_after_body():
    caption = build_caption(sample_card(), signoff="탐정냥의 사건 보고 끝")
    assert caption.index("탐정냥 한마디: 도둑도") < caption.index("탐정냥의 사건 보고 끝") < caption.index("출처: 연합뉴스")


def test_render_every_layout(tmp_path: Path):
    r = Renderer("fonts/NotoSansKR.ttf", "detective_nyang")
    a, b = fake_photo(1), fake_photo(2)
    b.ai = True
    for layout in ["single", "split", "inset", "compare"]:
        card = sample_card().model_copy(update={
            "layout": layout,
            "image_a": ImageSpec(source="stock", stock_query="x", ai_prompt="", label="1799년"),
            "image_b": ImageSpec(source="ai", stock_query="y", ai_prompt="p", label="2026년"),
        })
        paths = r.render(card, tmp_path / layout, a, b)
        assert Image.open(paths[0]).size == (1080, 1350)


def test_validate_requires_second_image_for_multi_layout():
    card = sample_card().model_copy(update={"layout": "split"})
    assert "두 번째 이미지" in validate_card(card)


def test_caption_marks_ai_images():
    caption = build_caption(sample_card(), ["AI 생성 이미지", "A / Pexels"])
    assert "AI로 생성" in caption


def test_make_reel_creates_vertical_video(tmp_path: Path):
    from viralgram.reels import make_reel
    imgs = []
    for i in range(2):
        p = tmp_path / f"{i}.jpg"
        fake_photo(i + 1).image.resize((1080, 1350)).save(p)
        imgs.append(p)
    out = make_reel(imgs, tmp_path / "reel.mp4")
    assert out.exists() and out.stat().st_size > 10_000


def _fake_photo(size=(1200, 630)):
    """로고 필터를 통과하는, 대비 있는 가짜 사진 (가로 줄무늬)."""
    from PIL import ImageDraw
    img = Image.new("RGB", size, "#203040")
    d = ImageDraw.Draw(img)
    for i in range(0, size[1], 40):
        d.rectangle((0, i, size[0], i + 20), fill=(200, 160 + i % 80, 90))
    return img


def test_article_image_skips_already_used(monkeypatch):
    from types import SimpleNamespace
    import viralgram.photos as P

    pages = {
        "https://a.kr/1": '<meta property="og:image" content="https://img/x.jpg">',
        "https://b.kr/2": '<meta property="og:image" content="https://img/x.jpg">',  # 같은 사진 (통신사 배포)
        "https://c.kr/3": '<meta property="og:image" content="https://img/y.jpg">',
    }
    monkeypatch.setattr(P.requests, "get", lambda url, **k: SimpleNamespace(
        text=pages[url], url=url, raise_for_status=lambda: None))
    monkeypatch.setattr(P, "_download_one", lambda url, min_side=700: _fake_photo())
    used: set[str] = set()
    first = P.fetch_article_image(list(pages), "연합뉴스", used)
    second = P.fetch_article_image(list(pages), "연합뉴스", used)
    third = P.fetch_article_image(list(pages), "연합뉴스", used)
    assert first and second and third is None
    assert used == {"https://img/x.jpg", "https://img/y.jpg"}


def test_split_of_two_landscape_photos_stacks_vertically(tmp_path: Path):
    r = Renderer("fonts/NotoSansKR.ttf", "detective_nyang")
    a = Photo(Image.new("RGB", (1600, 900), "#3a6ea5"), "A")
    b = Photo(Image.new("RGB", (1600, 900), "#a55a3a"), "B")
    img = r.compose("split", a, b)
    top, bottom = img.getpixel((540, 300)), img.getpixel((540, 1050))
    assert top[2] > top[0] and bottom[0] > bottom[2]  # 위는 파랑, 아래는 갈색 (좌우가 아니라 위아래)
    assert img.getpixel((200, 700)) == img.getpixel((900, 700))  # 같은 가로줄은 한 사진


def test_gather_images_always_uses_article_photo_as_thumbnail(monkeypatch):
    import viralgram.__main__ as M
    from viralgram.config import Settings
    cover = Photo(Image.new("RGB", (800, 800)), "뉴시스")
    monkeypatch.setattr(M, "fetch_article_image", lambda urls, credit, used: None)
    ai_a = ImageSpec(source="ai", stock_query="x", ai_prompt="p", label="")
    card = sample_card().model_copy(update={"image_a": ai_a})  # Claude 가 AI/무료 사진을 골라도
    a, b, extra = M.gather_images(card, Settings(), [], cover, set())
    assert a is cover and b is None and extra is None


def test_looks_like_logo():
    import random
    from PIL import Image, ImageDraw
    from viralgram.photos import looks_like_logo

    logo = Image.new("RGB", (800, 800), "#222222")
    ImageDraw.Draw(logo).ellipse((350, 350, 450, 450), fill="#FFFFFF")
    assert looks_like_logo(logo)
    assert looks_like_logo(Image.new("RGB", (1200, 630), "#888888"))
    assert looks_like_logo(Image.new("RGB", (1200, 630), "#888888").copy(), "https://x.com/img/logo.png")
    assert not looks_like_logo(_fake_photo())


def test_post_mode_by_time_and_feeds():
    from datetime import datetime, timedelta, timezone
    from viralgram.config import resolve_mode
    from viralgram.sources import feeds_for, FUNNY_FEEDS, ISSUE_FEEDS

    kst = timezone(timedelta(hours=9))
    assert resolve_mode("auto", datetime(2026, 10, 2, 12, 27, tzinfo=kst)) == "issue"
    assert resolve_mode("auto", datetime(2026, 10, 2, 20, 57, tzinfo=kst)) == "funny"
    assert resolve_mode("auto", datetime(2026, 10, 2, 11, 57, tzinfo=timezone.utc)) == "funny"  # 20:57 KST
    assert resolve_mode("issue", datetime(2026, 10, 2, 21, 0, tzinfo=kst)) == "issue"
    assert feeds_for("funny") is FUNNY_FEEDS and feeds_for("issue") is ISSUE_FEEDS
