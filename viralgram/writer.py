"""Claude 로 후보 선정 → (선택) 웹 검색 사실 확인 → 한국어 카드뉴스 원고 작성."""

from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel, Field

from .sources import Story

log = logging.getLogger(__name__)

MAX_SLIDES = 5  # 표지 + 본문 + 마무리 = 최대 7장 (인스타 캐러셀 한도 10장)


class Selection(BaseModel):
    ranking: list[int] = Field(
        description="게시하기 좋은 순서대로 정렬한 후보 번호 (최대 5개). 부적합한 후보는 제외."
    )
    reason: str = Field(description="1순위를 고른 이유 한 문장")


PHOTO_QUERY_DESC = (
    "이 페이지 배경 사진을 무료 사진 사이트에서 찾을 영어 검색어. 1~2단어의 흔한 명사, 실존 인물 이름 금지 "
    "(예: 'wedding', 'office', 'golden retriever', 'money')"
)


class Slide(BaseModel):
    heading: str = Field(description="슬라이드 소제목, 12자 이내, 음슴체/명사형")
    body: str = Field(description="슬라이드 본문, 짧은 문장 1~2개·60자 이내, 음슴체")
    photo_query: str = Field(description=PHOTO_QUERY_DESC)


class CardNews(BaseModel):
    verified: bool = Field(
        description="원문 이야기의 핵심 사실(누가·무엇을·결말)이 리서치 노트에서 신뢰할 만한 매체로 확인되면 true, "
        "미확인·루머·반박된 내용이면 false"
    )
    hook: str = Field(description="표지 제목. 궁금해서 안 넘길 수 없는 한 줄, 20자 이내")
    subtitle: str = Field(description="표지 부제, 25자 이내")
    slides: list[Slide] = Field(description="본문 슬라이드 3~5장, 이야기 흐름대로 (마지막 본문에 반전/결말)")
    closing: str = Field(description="마지막 장 문구: 편이 갈리는 양자택일 질문 또는 친구 태그 유도, 35자 이내")
    caption: str = Field(description="인스타 캡션 본문 (해시태그·출처 표기 제외), 짧은 줄 4~8개, 150~350자, 음슴체")
    hashtags: list[str] = Field(description="'#'으로 시작하는 해시태그 10~20개, 한국어 위주")
    source_credit: str = Field(description="출처 표기, 예: '출처: BBC, 연합뉴스'")
    cover_photo_query: str = Field(description="표지용. " + PHOTO_QUERY_DESC)
    closing_photo_query: str = Field(description="마지막 장용. " + PHOTO_QUERY_DESC)

    @property
    def photo_queries(self) -> list[str]:
        """페이지 순서대로 (표지, 본문..., 마지막 장)."""
        return [self.cover_photo_query, *(s.photo_query for s in self.slides), self.closing_photo_query]


SYSTEM = """당신은 팔로워 수십만의 한국 인스타그램 '이슈/썰' 계정 운영자입니다.
국내외에서 "헐 이게 실화?" 소리가 나오는 이야기를 골라, 보자마자 친구를 태그하고 공유하게 만드는 카드뉴스를 만듭니다.

말투 (가장 중요):
- 인스타 이슈 계정 특유의 음슴체. "~했다고 함", "~라는데", "~인 상황", "근데 여기서 반전" 같은 톤.
- 문장은 짧게 끊고, 한 문장에 한 정보만. 존댓말(~했어요, ~습니다) 금지.
- 교훈·감성 에세이·인생 조언("~인 것 같아요", "기회는 언제든 온다", "마음에 남는다") 절대 금지.
- 판단은 독자에게 맡기고, 사실과 상황만 빠르게 보여준 뒤 반응을 유도.
- 좋은 예: "월급 300인데 축의금 50 냈다는 신입" / "근데 상사 반응이 더 충격임" / "여러분은 누구 편?"
- 나쁜 예: "이 이야기는 우리에게 많은 것을 생각하게 해요." / "지금의 자리가 끝이 아닐지도 몰라요."

원칙:
- 사실만 씁니다. 원문에 없는 수치·인물·대사를 지어내지 않습니다. 원문 문장은 그대로 옮기지 않고 재구성합니다.
- 사고·범죄 피해자, 사망, 재난, 정치·젠더·지역 갈등, 특정 일반인 신상·조롱 소재는 쓰지 않습니다.
- "확인된 건 여기까지", "세부 내용은 미확인" 같은 취재 과정·정보 부족 언급은 쓰지 않습니다."""


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
                        "아래 후보 중 인스타그램에서 조회수·공유가 폭발할 이야기를 골라 순위를 매겨주세요.\n"
                        "우선순위: ① 제목만 봐도 '헐' 소리 나는 충격·황당·반전 ② 댓글에서 편이 갈리는 논쟁거리 "
                        "(돈, 연애·결혼, 직장, 매너, 세대 차이 등 생활 밀착형) ③ 친구를 태그하고 싶은 웃기거나 신기한 이야기.\n"
                        "밋밋한 미담, 기업 홍보성 기사, 정보가 너무 적어 이야기가 안 되는 후보는 뒤로 미루거나 제외하세요.\n"
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
                        "표지(어그로 한 줄) → 본문(상황 → 전개 → 반전/결말) → 편 가르기 질문 순서입니다.\n"
                        "캡션 첫 줄은 피드에서 '더 보기'를 누르게 만드는 한 줄로 시작하고, 끝은 댓글·태그 유도로 마무리하세요.\n"
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
