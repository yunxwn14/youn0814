"""국내/해외 화제성 이야기 후보 수집 (RSS)."""

from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import quote_plus

import feedparser
import requests

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; viralgram/1.0; +https://github.com)"


def google_news(query: str, lang: str = "ko") -> str:
    if lang == "ko":
        return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ko&gl=KR&ceid=KR:ko"
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


# (지역, 피드 URL). 필요에 따라 자유롭게 추가/삭제하세요.
DEFAULT_FEEDS: list[tuple[str, str]] = [
    # 국내 — 누리꾼 반응이 뜨겁거나 편이 갈리는 생활 밀착형 이슈 위주
    ("국내", google_news("누리꾼 갑론을박 when:2d")),
    ("국내", google_news("누리꾼 경악 OR 분노 OR 황당 when:2d")),
    ("국내", google_news("온라인 커뮤니티 난리 OR 발칵 when:2d")),
    ("국내", google_news("충격 반전 when:2d")),
    ("국내", google_news("웃픈 OR 폭소 OR 빵터진 사연 when:3d")),
    ("국내", google_news("이색 해프닝 OR 웃음 when:3d")),
    ("국내", google_news("역대급 화제 when:2d")),
    ("국내", google_news("사연 공분 OR 사이다 when:2d")),
    ("국내", google_news("진상 손님 OR 빌런 OR 무개념 when:3d")),
    ("국내", google_news("축의금 OR 더치페이 OR 결혼식 논란 when:3d")),
    ("국내", google_news("신입사원 OR 직장인 OR MZ 논란 when:3d")),
    ("국내", google_news("연봉 OR 월급 OR 알바 논란 when:3d")),
    ("국내", google_news("층간소음 OR 주차 OR 배달 논란 when:3d")),
    # 해외
    ("해외", google_news("sparks outrage OR backlash online when:2d", lang="en")),
    ("해외", google_news("internet divided OR sparks debate when:2d", lang="en")),
    ("해외", google_news("goes viral when:2d", lang="en")),
    ("해외", google_news("hilarious OR funny viral story when:3d", lang="en")),
    ("해외", google_news("bizarre OR unbelievable OR shocking when:2d", lang="en")),
    ("해외", google_news("customer OR boss OR wedding viral story when:3d", lang="en")),
    ("해외", "https://www.reddit.com/r/nottheonion/top/.rss?t=day"),
]


@dataclass
class Story:
    region: str
    title: str
    summary: str
    link: str
    source: str

    @property
    def id(self) -> str:
        """중복 게시 방지용 키. 제목 기준 (같은 기사가 여러 매체에 실려도 걸러지도록 정규화)."""
        norm = re.sub(r"\W+", "", self.title.lower())
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", text or ""))).strip()


def _split_source(title: str, entry) -> tuple[str, str]:
    """구글 뉴스 제목은 '기사 제목 - 매체명' 형태라 매체명을 분리한다."""
    source = ""
    src = entry.get("source")
    if isinstance(src, dict):
        source = src.get("title", "")
    if source and title.endswith(f" - {source}"):
        title = title[: -len(source) - 3]
    elif not source and " - " in title and "news.google" in entry.get("link", ""):
        title, source = title.rsplit(" - ", 1)
    return title.strip(), source.strip()


def parse_feed(region: str, content: bytes | str, limit: int = 15) -> list[Story]:
    feed = feedparser.parse(content)
    feed_title = _clean(feed.feed.get("title", ""))
    stories = []
    for entry in feed.entries[:limit]:
        title, source = _split_source(_clean(entry.get("title", "")), entry)
        if not title:
            continue
        stories.append(
            Story(
                region=region,
                title=title,
                summary=_clean(entry.get("summary", ""))[:500],
                link=entry.get("link", ""),
                source=source or feed_title,
            )
        )
    return stories


def fetch_candidates(
    feeds: list[tuple[str, str]] | None = None, exclude_ids: set[str] | None = None
) -> list[Story]:
    """모든 피드에서 후보를 모아 중복/이미 게시한 것을 제거해 반환.
    앞쪽 피드만 뽑히지 않도록 피드별 1순위, 2순위... 순서로 번갈아 섞는다."""
    exclude_ids = exclude_ids or set()
    per_feed: list[list[Story]] = []
    for region, url in feeds or DEFAULT_FEEDS:
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("피드 수집 실패 (%s): %s", url, exc)
            continue
        per_feed.append(parse_feed(region, resp.content))
    seen: set[str] = set()
    result: list[Story] = []
    for rank in range(max((len(f) for f in per_feed), default=0)):
        for stories in per_feed:
            if rank < len(stories):
                story = stories[rank]
                if story.id not in seen and story.id not in exclude_ids:
                    seen.add(story.id)
                    result.append(story)
    log.info("후보 %d건 수집", len(result))
    return result
