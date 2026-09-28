from pathlib import Path

from PIL import Image

from viralgram.cards import Renderer
from viralgram.history import History
from viralgram.sources import parse_feed
from viralgram.writer import CardNews, Slide, build_caption

GOOGLE_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Google 뉴스</title>
<item><title>고양이가 편의점 점장이 됐다 - 연합뉴스</title><link>https://news.google.com/a</link>
<description>&lt;a href="x"&gt;고양이&lt;/a&gt; 점장 이야기</description><source url="https://yna.co.kr">연합뉴스</source></item>
<item><title>고양이가 편의점 점장이 됐다 - 연합뉴스</title><link>https://news.google.com/b</link></item>
</channel></rss>"""


def sample_card() -> CardNews:
    return CardNews(
        hook="편의점 점장이 된 고양이, 매출이 두 배로?",
        subtitle="손님들이 줄 서서 기다린다는 그 가게",
        slides=[
            Slide(heading="어느 날 나타난 길고양이", body="추운 겨울, 가게 앞에서 떨던 고양이를 점주가 들여보냈대요."),
            Slide(heading="명예 점장 임명", body="이름표까지 달아줬더니 SNS 에서 입소문이 났다고 함. " * 2),
            Slide(heading="반전 결말", body="지금은 고양이 보러 오는 손님 덕에 매출이 크게 늘었대요."),
        ],
        closing="여러분 동네에도 이런 가게 있나요?",
        caption="고양이 한 마리가 동네 편의점을 바꿔놓았습니다.\n\n자세한 이야기는 카드에서!",
        hashtags=["#고양이", "편의점", "#고양이", "#훈훈한 이야기"],
        source_credit="출처: 연합뉴스",
    )


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
    assert caption.count("#고양이") == 1
    assert "#훈훈한이야기" in caption and "#편의점" in caption
    assert "출처: 연합뉴스" in caption
    assert len(caption) <= 2200


def test_render_cards(tmp_path: Path):
    paths = Renderer("fonts/NotoSansKR.ttf", "@viral_story").render(sample_card(), "국내", tmp_path)
    assert len(paths) == 5
    assert Image.open(paths[0]).size == (1080, 1350)
