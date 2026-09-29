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
        hashtags=["#금붕어", "도둑", "#금붕어", "#해외 이슈"],
        source_credit="출처: 연합뉴스",
        article_url="",
        layout="single",
        image_a=ImageSpec(source="stock", stock_query="goldfish", ai_prompt="", label=""),
        image_b=None,
        extra_photo_query="kitchen sink",
    )


def test_photo_queries_follow_page_order():
    assert sample_card().photo_queries == ["goldfish", "kitchen sink"]
    card = sample_card().model_copy(update={"layout": "split", "image_b": ImageSpec(
        source="ai", stock_query="thief", ai_prompt="a burglar", label="")})
    assert card.photo_queries == ["goldfish", "thief", "kitchen sink"]


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
    assert len(paths) == 1
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
    assert len(paths) == 2  # 썸네일 + 글씨 없는 사진
    assert all(Image.open(p).size == (1080, 1350) for p in paths)


def test_caption_includes_photo_credits():
    caption = build_caption(sample_card(), ["A / Pexels", "A / Pexels", "B / Pexels"])
    assert "사진: A / Pexels, B / Pexels" in caption


def test_validate_card_rejects_broken_output():
    assert validate_card(sample_card()) == ""
    assert "한글" in validate_card(sample_card().model_copy(update={"headline": '"\U0001f608\ufe0f\U0001f609"'}))
    assert "문자" in validate_card(sample_card().model_copy(update={"headline": "성묘 갔더니 할머니 산소 앞\n골프 연습 \U0001f3cc"}))
    assert "검색어" in validate_card(sample_card().model_copy(update={"extra_photo_query": " "}))


def test_validate_card_rejects_vague_headline():
    card = sample_card().model_copy(update={"headline": "1500만원 골드바 내밀며\n며느리에게 '이것' 양보 종용"})
    assert "숨김" in validate_card(card)


def test_caption_signoff_after_body():
    caption = build_caption(sample_card(), signoff="탐정냥의 사건 보고 끝")
    assert caption.index("탐정냥의 사건 보고 끝") < caption.index("출처: 연합뉴스")


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
