"""Claude 로 후보 선정 → (선택) 웹 검색 사실 확인 → 한국어 카드뉴스 원고 작성."""

from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel, Field

from .sources import Story

log = logging.getLogger(__name__)

MAX_SLIDES = 6  # 표지 + 본문 + 마무리 = 최대 8장 (인스타 캐러셀 한도 10장)


class Selection(BaseModel):
    ranking: list[int] = Field(
        description="게시하기 좋은 순서대로 정렬한 후보 번호 (최대 5개). 부적합한 후보는 제외."
    )
    reason: str = Field(description="1순위를 고른 이유 한 문장")


class Slide(BaseModel):
    heading: str = Field(description="슬라이드 소제목, 15자 이내")
    body: str = Field(description="슬라이드 본문, 2~3문장·90자 이내, 구어체")


class CardNews(BaseModel):
    verified: bool = Field(
        description="원문 이야기의 핵심 사실(누가·무엇을·결말)이 리서치 노트에서 신뢰할 만한 매체로 확인되면 true, "
        "미확인·루머·반박된 내용이면 false"
    )
    hook: str = Field(description="표지 제목. 스크롤을 멈추게 하는 한 줄, 22자 이내")
    subtitle: str = Field(description="표지 부제, 30자 이내")
    slides: list[Slide] = Field(description="본문 슬라이드 3~6장, 이야기 흐름대로")
    closing: str = Field(description="마지막 장 문구: 댓글을 유도하는 질문, 40자 이내")
    caption: str = Field(description="인스타 캡션 본문 (해시태그·출처 표기 제외), 줄바꿈 포함 300~600자")
    hashtags: list[str] = Field(description="'#'으로 시작하는 해시태그 10~20개, 한국어 위주")
    source_credit: str = Field(description="출처 표기, 예: '출처: BBC, 연합뉴스'")
    photo_queries: list[str] = Field(
        description="무료 사진 사이트에서 검색할 영어 키워드 3개. 실존 인물 이름 없이 장면·사물·분위기로 "
        "(예: 'message in a bottle on beach', 'golden retriever portrait'). 첫 번째가 표지용"
    )


SYSTEM = """당신은 한국 인스타그램 '썰/이슈' 카드뉴스 계정의 에디터입니다.
국내외의 재미있고, 황당하고, 훈훈한 실제 이야기를 골라 20~30대가 저장·공유하고 싶어지는 카드뉴스로 만듭니다.

원칙:
- 사실만 씁니다. 원문이나 검색으로 확인되지 않은 수치·인물·대사를 지어내지 않습니다.
- 원문 문장을 그대로 옮기지 말고 자신의 말로 재구성합니다. 출처 매체는 반드시 표기합니다.
- 사고·범죄 피해자, 사망, 재난, 정치적 갈등, 특정 일반인을 조롱하는 소재는 고르지 않습니다.
- 말투는 친근한 구어체(~했대요, ~라고 함 등)로, 과장된 낚시나 혐오 표현은 쓰지 않습니다.
- 카드와 캡션에 "확인된 건 여기까지", "세부 내용은 미확인" 같은 취재 과정·정보 부족 언급을 쓰지 않습니다.
  정보가 적으면 아는 사실만으로 짧고 임팩트 있게 쓰고, 나머지는 공감·질문·반응 포인트로 채웁니다."""


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
                        "아래 후보 중 인스타그램에서 바이럴될 가능성이 높은 이야기를 골라 순위를 매겨주세요.\n"
                        "기준: 첫 줄만 봐도 궁금한가, 댓글로 의견을 나누고 싶은가, 친구를 태그하고 싶은가.\n"
                        "최근 게시물과 비슷한 소재는 피하고, 국내/해외가 적당히 섞이도록 해주세요.\n\n"
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
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
        messages = [
            {
                "role": "user",
                "content": (
                    "다음 이야기를 웹에서 검색해 사실관계를 확인하고, 카드뉴스에 쓸 핵심 사실을 정리해주세요.\n"
                    "누가/언제/어디서/무슨 일이/결말, 흥미로운 디테일, 신뢰할 만한 출처 매체명을 bullet 로.\n"
                    "확인되지 않는 부분은 '미확인'이라고 적어주세요.\n\n"
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
    def write(self, story: Story, notes: str) -> CardNews:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "아래 이야기로 인스타그램 캐러셀 카드뉴스 원고를 써주세요.\n"
                        "표지 → 본문(발단·전개·반전/결말) → 댓글 유도 질문 순서입니다.\n"
                        "캡션 첫 줄은 피드에서 '더 보기'를 누르게 만드는 문장으로 시작하세요.\n"
                        f"이 이야기는 {story.region} 소식입니다. 해시태그도 이에 맞게(국내면 #국내이슈 등) 달아주세요.\n\n"
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
        if notes and not card.verified:
            raise WriterRefusal("사실 확인이 안 되는 이야기라 건너뜀")
        card.slides = card.slides[:MAX_SLIDES]
        return card

    @staticmethod
    def _check(response) -> None:
        if response.stop_reason == "refusal":
            raise WriterRefusal(getattr(response.stop_details, "explanation", "") or "refusal")
        if response.stop_reason == "max_tokens":
            raise WriterRefusal("응답이 max_tokens 에서 잘림")


def build_caption(card: CardNews, photo_credits: list[str] | None = None, max_hashtags: int = 25) -> str:
    """인스타 캡션: 본문 + 출처 + 해시태그 (2,200자·해시태그 30개 제한 준수)."""
    tags = []
    for tag in card.hashtags:
        tag = "#" + tag.lstrip("#").replace(" ", "")
        if len(tag) > 1 and tag not in tags:
            tags.append(tag)
    tags = tags[:max_hashtags]
    body, credit = card.caption.strip(), card.source_credit.strip()
    if credit and credit not in body:
        body = f"{body}\n\n{credit}"
    if photo_credits:
        body += "\n사진: " + ", ".join(dict.fromkeys(photo_credits))
    caption = f"{body}\n\n{' '.join(tags)}"
    return caption[:2200]
