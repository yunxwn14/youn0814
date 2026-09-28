# viralgram — 화제 이야기 인스타그램 자동 게시기

국내외의 재미있고 황당하고 훈훈한 이야기를 자동으로 찾아서, 한국어 **카드뉴스(캐러셀)**로 만든 뒤 인스타그램에 게시합니다.

```
뉴스/레딧 RSS 수집 ─▶ Claude가 바이럴 가능성 순위 매김 ─▶ 웹 검색으로 사실 확인
      ─▶ 한국어 카드뉴스 원고 + 캡션 + 해시태그 작성 ─▶ 1080×1350 카드 이미지 생성
      ─▶ 이미지 공개 URL 업로드 ─▶ Instagram Graph API 캐러셀 게시 ─▶ 이력 저장(중복 방지)
```

## 구성

| 파일 | 역할 |
|---|---|
| `viralgram/sources.py` | 구글 뉴스(국내·해외 키워드), 레딧(r/nottheonion 등) RSS 수집. `DEFAULT_FEEDS` 에서 소스 편집 |
| `viralgram/writer.py` | Claude API로 후보 선정 → 웹 검색 리서치 → 카드뉴스 원고(구조화 출력) |
| `viralgram/cards.py` | Pillow로 표지/본문/마무리 카드 렌더링 (테마 5종 순환) |
| `viralgram/hosting.py` | 이미지를 imgbb 또는 GitHub(공개 저장소)에 올려 공개 URL 확보 |
| `viralgram/instagram.py` | Graph API 캐러셀 게시 (컨테이너 생성 → 처리 대기 → 발행) |
| `viralgram/history.py` | `data/posted.json` 에 게시 이력 기록 |
| `.github/workflows/post.yml` | 하루 3회(한국시간 08:57 / 12:27 / 20:57) 자동 실행 |

## 1. 준비물

1. **인스타그램 프로페셔널 계정** (비즈니스 또는 크리에이터)
2. **Meta 개발자 앱** — [developers.facebook.com](https://developers.facebook.com) 에서 앱 생성 후 Instagram API 추가
   - 권한: `instagram_basic`, `instagram_content_publish` (페이스북 로그인 방식) 또는 `instagram_business_basic`, `instagram_business_content_publish` (인스타그램 로그인 방식)
   - **장기 액세스 토큰**(60일)과 **인스타그램 사용자 ID** 발급. 토큰은 만료 전 갱신 필요
   - 인스타그램 로그인 방식 토큰(`IGAA...`)이면 접속 주소와 사용자 ID 를 자동으로 찾으므로 토큰만 있으면 됩니다
3. **Anthropic API 키** — [console.anthropic.com](https://console.anthropic.com)
4. **이미지 호스팅** — [imgbb API 키](https://api.imgbb.com)(무료) 권장. 또는 이 저장소가 공개라면 `IMAGE_HOST=github`

## 2. 로컬에서 실행

```bash
pip install -r requirements.txt
mkdir -p fonts && curl -sSL -o fonts/NotoSansKR.ttf \
  "https://raw.githubusercontent.com/google/fonts/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf"
cp .env.example .env   # 값 채우기

python -m viralgram --dry-run   # 게시 없이 output/ 에 카드와 캡션만 생성 → 먼저 결과물 확인!
python -m viralgram             # 실제 게시
```

## 3. GitHub Actions로 자동 게시

저장소 **Settings → Secrets and variables → Actions** 에 등록:

- Secrets: `ANTHROPIC_API_KEY`, `IG_ACCESS_TOKEN`, `IMGBB_API_KEY` (페이스북 로그인 토큰이면 `IG_USER_ID` 도)
- Variables(선택): `BRAND_HANDLE`(예: `@my_viral_story`), `IMAGE_HOST`, `IG_GRAPH_HOST`

그 후 **Actions → Instagram 자동 게시 → Run workflow** 에서 `dry_run` 체크로 먼저 테스트하세요. 생성된 카드는 실행 결과의 Artifacts 에서 받아볼 수 있습니다. 게시 시간은 `post.yml` 의 `cron` 을 수정하면 됩니다.

## 커스터마이징

- **소재 바꾸기**: `sources.py` 의 `DEFAULT_FEEDS` 키워드 수정 (예: `google_news("동물 사연 when:2d")`)
- **말투/편집 방향**: `writer.py` 의 `SYSTEM` 프롬프트
- **디자인**: `cards.py` 의 `THEMES`, 폰트 크기, 레이아웃
- **비용 절감**: `.env` 에서 `WEB_RESEARCH=false` (사실 확인 단계 생략), `CLAUDE_MODEL=claude-sonnet-5`

## 운영 시 주의

- **저작권**: 원문을 그대로 옮기지 않고 재구성하며 출처를 표기하도록 되어 있지만, 기사 사진은 사용하지 않습니다(텍스트 카드만). 게시 전 dry-run 으로 품질을 확인하는 걸 권장합니다.
- **사실 확인**: 웹 검색으로 확인하도록 했지만 AI가 틀릴 수 있습니다. 초기엔 dry-run 결과를 보고 수동 게시하다가 품질이 안정되면 자동화하세요.
- **인스타 제한**: Graph API 게시는 계정당 24시간 50건 제한. 과도한 자동 게시는 도달률 저하나 제재 원인이 될 수 있어 하루 2~4회를 권장합니다.
- **레딧 RSS** 는 클라우드 IP에서 차단될 때가 있습니다. 실패한 피드는 건너뛰고 나머지로 진행합니다.

## 테스트

```bash
pytest -q
```
