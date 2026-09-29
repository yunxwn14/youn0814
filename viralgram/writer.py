"""Claude 로 후보 선정 → (선택) 웹 검색 사실 확인 → 한국어 카드뉴스 원고 작성."""

from __future__ import annotations

import logging
import re

import anthropic
from pydantic import BaseModel, Field

from .sources import Story

log = logging.getLogger(__name__)

class Selection(BaseModel):
    ranking: list[int] = Field(
        description="게시하기 좋은 순서대로 정렬한 후보 번호 (최대 5개). 부적합한 후보는 제외."
    )
    reason: str = Field(description="1순위를 고른 이유 한 문장")


PHOTO_QUERY_DESC = (
    "무료 사진 사이트에서 찾을 영어 검색어. 1~2단어의 흔한 명사, 실존 인물 이름 금지 "
    "(예: 'goldfish', 'bank', 'call center', 'violin')"
)


class CardNews(BaseModel):
    headline: str = Field(
        description="썸네일 제목. 정확히 2줄, 줄 사이는 '\\n'. 각 줄 15자 안팎. 핵심 키워드는 작은따옴표로 강조 "
        "(예: \"은행 영업시간 이제 '30분'\\n짧아진다, 금융노사 합의완료\")"
    )
    body: str = Field(description="캡션 본문. 뉴스체 존댓말(~습니다) 2~3문장, 120~250자. 원문에 있는 사실만")
    hashtags: list[str] = Field(description="'#'으로 시작하는 해시태그 3~6개")
    source_credit: str = Field(description="출처 표기, 예: '출처: 연합뉴스'")
    cover_photo_query: str = Field(description="썸네일 배경용. 이야기 핵심 장면이 떠오르는 사진. " + PHOTO_QUERY_DESC)
    extra_photo_query: str = Field(description="글씨 없이 두 번째 장에 쓸 사진. " + PHOTO_QUERY_DESC)

    @property
    def photo_queries(self) -> list[str]:
        return [self.cover_photo_query, self.extra_photo_query]


SYSTEM = """당신은 한국 인스타그램 이슈 매거진 계정의 에디터입니다.
국내외에서 "헐 이게 실화?" 소리가 나오는 이야기를 골라, 썸네일 한 장으로 공유와 댓글을 유도합니다.

썸네일 제목 (가장 중요):
- 제목만 읽어도 "누가 / 무엇을 했고 / 어떻게 됐는지"가 한 번에 이해돼야 함. 캡션을 안 읽어도 내용을 알 수 있게.
- '이것', '이렇게', '그 이유', '충격 행동' 처럼 핵심을 숨기는 표현 금지. 숨기지 말고 구체적 사실(무엇을·얼마를·왜)을 그대로 씀.
- 자극은 숨김이 아니라 구체적 사실의 대비·반전에서 나옴 (예: 도둑인데 금붕어를 살려줌, 콜센터 직원이 통화 중 베이컨을 구움).
- 2줄. 핵심 단어는 '작은따옴표'로 강조. 기사 제목처럼 명사·단정형으로 끝냄 ("~화제", "~결국 해고", "~'연구결과'").
- 좋은 예: "실수로 어항 깨자, 싱크대에\n물받아 금붕어 살려준 도둑들" / "콜센터 직원, 통화 길어지자\n베이컨 구워먹어 결국 해고" / "은행 영업시간 이제 '30분'\n짧아진다, 금융노사 합의완료"
- 나쁜 예: "며느리에게 양보 종용한\n시어머니" (무엇을 양보하라는지 모름) / "성묘 갔다가\n충격 목격" (무엇을 봤는지 모름)

캡션 본문:
- 담백한 뉴스체 존댓말(~습니다, ~했습니다). 2~3문장으로 무슨 일인지만 전달.
- 교훈·감상·질문·이모지 없이 사실만.

원칙:
- 원문에 없는 수치·인물·대사를 지어내지 않습니다. 원문 문장은 그대로 옮기지 않고 재구성합니다.
- 사고·범죄 피해자, 사망, 재난, 정치·젠더·지역 갈등, 특정 일반인 신상·조롱 소재는 쓰지 않습니다.
- "확인된 건 여기까지" 같은 취재 과정·정보 부족 언급은 쓰지 않습니다."""


class WriterRefusal(Exception):
    pass


class Writer:
    def __init__(self, model: str, web_research: bool = True):
        self.client = anthropic.Anthropic()
        self.model = model
        self.web_research = web_research

    # ── 1) 후보 선정 ─────────────────────────────────────
    def rank(self, stories: list[Story], recent_titles: list[str]) -> list[Story]:
        listing = "\n".join(
            f"[{i}] ({s.region}) {s.title} — {s.source}\n    {s.summary[:200]}"
            for i, s in enumerate(stories)
        )
        recent = "\n".join(f"- {t}" for t in recent_titles) or "(없음)"
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
            output_config={"effort": "low"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        "아래 후보 중 인스타그램에서 조회수·공유·댓글이 폭발할 이야기를 골라 순위를 매겨주세요.\n"
                        "우선순위: ① 댓글창에서 편이 확 갈리거나 공분·경악이 터질 이야기 (돈, 연애·결혼, 직장, 매너, 진상, 세대 차이 등 "
                        "생활 밀착형) ② 제목만 봐도 '헐' 소리 나는 충격·황당·반전 ③ 친구를 태그하고 싶은 어이없거나 신기한 이야기.\n"
                        "'나라면?', '누구 잘못?' 같은 반응이 바로 나오는 소재일수록 높게 쳐주세요.\n"
                        "밋밋한 미담, 기업·지자체 홍보성 기사, 정책 발표, 정보가 너무 적어 이야기가 안 되는 후보는 제외하세요.\n"
                        "최근 게시물과 비슷한 소재는 피해주세요.\n\n"
                        f"## 최근 게시한 제목\n{recent}\n\n## 후보\n{listing}"
                    ),
                }
            ],
            output_format=Selection,
        )
        self._check(response)
        picked = [stories[i] for i in response.parsed_output.ranking if 0 <= i < len(stories)]
        log.info("선정 이유: %s", response.parsed_output.reason)
        return picked

    # ── 2) 웹 검색으로 사실 확인/보강 ───────────────────────
    def research(self, story: Story) -> str:
        if not self.web_research:
            return ""
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}]
        messages = [
            {
                "role": "user",
                "content": (
                    "다음 기사를 웹에서 찾아 실제로 무슨 일이 있었는지 구체적으로 정리해주세요. 검색은 꼭 필요한 만큼만.\n"
                    "제목이 '이것', '이렇게'처럼 핵심을 숨겼다면 그게 정확히 무엇인지 반드시 밝혀주세요.\n"
                    "누가/무엇을/얼마나/왜/결말, 사람들 반응, 매체명을 짧은 bullet 로.\n\n"
                    f"제목: {story.title}\n요약: {story.summary}\n출처: {story.source}\n링크: {story.link}"
                ),
            }
        ]
        response = None
        for _ in range(5):  # pause_turn 이어받기 한도
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                messages=messages,
                tools=tools,
            )
            if response.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": response.content}]
        self._check(response)
        notes = "\n".join(b.text for b in response.content if b.type == "text").strip()
        log.info("리서치 노트 %d자", len(notes))
        return notes

    # ── 3) 카드뉴스 원고 작성 ──────────────────────────────
    def _write_once(self, story: Story, notes: str) -> CardNews:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "아래 이야기로 인스타그램 게시물(썸네일 제목 + 짧은 캡션)을 써주세요.\n"
                        f"이 이야기는 {story.region} 소식입니다.\n\n"
                        f"## 원문 정보\n제목: {story.title}\n요약: {story.summary}\n"
                        f"매체: {story.source}\n링크: {story.link}\n\n"
                        f"## 리서치 노트\n{notes or '(없음 — 원문 정보에 있는 사실만 사용)'}"
                    ),
                }
            ],
            output_format=CardNews,
        )
        self._check(response)
        card = response.parsed_output
        return card

    def write(self, story: Story, notes: str, attempts: int = 3) -> CardNews:
        """원고를 쓰고 검사한다. 제목이 깨졌거나 사진 검색어가 비는 등 이상하면 다시 쓴다."""
        problem = ""
        for _ in range(attempts):
            card = self._write_once(story, notes)
            problem = validate_card(card)
            if not problem:
                return card
            log.warning("원고 검사 실패, 다시 작성: %s", problem)
        raise WriterRefusal(f"원고 검사 {attempts}회 실패: {problem}")

    @staticmethod
    def _check(response) -> None:
        if response.stop_reason == "refusal":
            raise WriterRefusal(getattr(response.stop_details, "explanation", "") or "refusal")
        if response.stop_reason == "max_tokens":
            raise WriterRefusal("응답이 max_tokens 에서 잘림")


_HANGUL = re.compile(r"[가-힣]")
# 한글·영문·숫자·흔한 문장부호만 허용 (이모지 등은 폰트에 없어 네모로 깨진다)
_ALLOWED = re.compile(r"^[가-힣ㄱ-ㅎa-zA-Z0-9\s'\"‘’“”.,!?·…~%&()\-+:/]+$")


_VAGUE = re.compile(r"이것|이거|이렇게|그것|충격 행동|충격적인 행동|그 이유")


def validate_card(card: CardNews) -> str:
    """문제가 있으면 이유를, 없으면 빈 문자열을 반환."""
    lines = [line for line in card.headline.split("\n") if line.strip()]
    if not 1 <= len(lines) <= 3:
        return f"제목 줄 수 이상 ({len(lines)}줄)"
    if len(_HANGUL.findall(card.headline)) < 8:
        return f"제목에 한글이 너무 적음: {card.headline!r}"
    if not _ALLOWED.match(card.headline):
        return f"제목에 쓸 수 없는 문자: {card.headline!r}"
    if len(card.headline) > 60:
        return "제목이 너무 김"
    if _VAGUE.search(card.headline):
        return f"제목이 핵심을 숨김: {card.headline!r}"
    if len(_HANGUL.findall(card.body)) < 30:
        return "본문이 너무 짧음"
    if not all(q.strip() for q in card.photo_queries):
        return "사진 검색어가 비어 있음"
    return ""


def build_caption(card: CardNews, photo_credits: list[str] | None = None, max_hashtags: int = 8) -> str:
    """인스타 캡션: [제목] + 본문 + 출처 + 해시태그 (2,200자 제한)."""
    tags = []
    for tag in card.hashtags:
        tag = "#" + tag.lstrip("#").replace(" ", "")
        if len(tag) > 1 and tag not in tags:
            tags.append(tag)
    title = " ".join(line.strip() for line in card.headline.split("\n") if line.strip())
    parts = [f"[{title}]", card.body.strip()]
    credit = card.source_credit.strip()
    if photo_credits:
        credit += "\n사진: " + ", ".join(dict.fromkeys(photo_credits))
    parts.append(credit.strip())
    if tags:
        parts.append(" ".join(tags[:max_hashtags]))
    return "\n\n".join(p for p in parts if p)[:2200]
