"""
generator.py (v4.1)
===================
ESG 기획기사 생성기 — 기획안 선행(Outline-First) 파이프라인.

v4.0 → v4.1 핵심 변경:
  - [문제] v4.0의 1단계가 One-shot 초안 생성이라 단순 나열식(Cataloging) 기사 산출
  - [해법] 인간 기자의 기획기사 작성 프로세스를 모사:
           테마 추출 → 논리 전개도(Outline) 작성 → 집필

시스템 프롬프트 구조 (v4.0과 동일):
  1. 역할 선언 (매우 간결)
  2. DATA 기사 전문 (최대한 많이 — 이것이 핵심)
  3. 구조적 청사진 (구체적 문단 흐름 템플릿)
  4. 표현 은행 (실제 문장·구문 수집)
  5. 목소리 가이드 (간결한 실전 지침)
  6. 정량 기준 (DATA 평균 ±5%)
  7. 보조 기술 지침 (번역투 회피 등)

파이프라인 (v4.1 — 6단계):
  [1단계] 기획안 생성 — 핵심 테마(Narrative Anchor) + 문단별 논리 전개도(Outline)
  [2단계] 초안 집필 — 기획안을 골격으로 DATA 문체로 작성
  [3단계] DATA 대조 검증 — DATA 기사와 직접 비교하여 유사도 점검
  [4단계] 보도자료 반영도 검증 — 빠짐없는 반영 확인
  [5단계] 정량 지표 검증 — DATA 수치와 비교
  [6단계] 최종 교정 — DATA 기사를 참조하여 교정
"""

import os
import re
import time
from typing import Optional, Generator

import anthropic


class ArticleGenerator:
    """ESG 기획기사 기획안 선행(Outline-First) 생성기."""

    MODELS = {
        "sonnet": "claude-sonnet-4-20250514",
        "haiku": "claude-haiku-4-5-20251001",
        "opus": "claude-opus-4-0-20250115",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "sonnet",
        max_tokens: int = 8192,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        self.client = anthropic.Anthropic(
            api_key=self.api_key,
            timeout=300.0,  # 5분 타임아웃
        )
        self.model_id = self.MODELS.get(model, model)
        self.max_tokens = max_tokens

    def _api_call_with_retry(self, max_retries: int = 3, **kwargs):
        """API 호출을 rate limit 및 타임아웃 재시도 로직과 함께 수행한다."""
        for attempt in range(max_retries):
            try:
                return self.client.messages.create(**kwargs)
            except anthropic.RateLimitError:
                if attempt == max_retries - 1:
                    raise
                wait = 60 * (attempt + 1) + 10
                print(f"    Rate limit 도달. {wait}초 대기 후 재시도 ({attempt+1}/{max_retries})...")
                time.sleep(wait)
            except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
                if attempt == max_retries - 1:
                    raise
                wait = 30 * (attempt + 1)
                print(f"    연결 오류. {wait}초 대기 후 재시도 ({attempt+1}/{max_retries})...")
                time.sleep(wait)

    # ===================================================================
    # 시스템 프롬프트 구축
    # ===================================================================

    def build_system_prompt(
        self,
        blueprint: str,
        voice: str,
        example_articles: list[dict],
        metrics: Optional[dict] = None,
    ) -> str:
        """
        시스템 프롬프트를 구축한다.

        핵심 원칙: DATA 기사 전문이 가장 큰 비중을 차지한다.
        구조 청사진과 표현 은행은 DATA를 구체적으로 분석한 결과이므로,
        DATA 기사 자체 다음으로 높은 비중을 갖는다.
        """
        # DATA 기사 블록 (전문)
        examples_block = "\n\n---\n\n".join(
            f"### DATA 기사 {i+1}: {art['title']}\n\n{art['text']}"
            for i, art in enumerate(example_articles)
        )

        # 정량 기준 블록
        metrics_block = ""
        if metrics and metrics.get("bounds"):
            b = metrics["bounds"]
            sub_info = ""
            if metrics.get("avg_subheading_count", 0) > 0:
                sub_info = f"\n| 중간제목 수 | {metrics['avg_subheading_count']:.1f}개 | — | — |"
                if metrics.get("avg_paras_per_subheading", 0) > 0:
                    sub_info += f"\n| 중간제목 간격 | {metrics['avg_paras_per_subheading']:.1f}문단마다 | — | — |"

            metrics_block = f"""
# 5. DATA 기사 정량 기준 (±5% 이내 준수)

| 항목 | DATA 평균 | 허용 최소 | 허용 최대 |
|------|-----------|-----------|-----------|
| 기사 총 길이(본문) | {metrics['avg_article_length']:,.0f}자 | {b['article_length_min']:,.0f}자 | {b['article_length_max']:,.0f}자 |
| 문단 수 | {metrics['avg_paragraph_count']:.1f}개 | {b['paragraph_count_min']:.1f}개 | {b['paragraph_count_max']:.1f}개 |
| 문단 평균 길이 | {metrics['avg_paragraph_length']:,.0f}자 | {b['paragraph_length_min']:,.0f}자 | {b['paragraph_length_max']:,.0f}자 |
| 문장 평균 길이 | {metrics['avg_sentence_length']:.0f}자 | {b['sentence_length_min']:.0f}자 | {b['sentence_length_max']:.0f}자 |
| 첫 문장 평균 길이 | {metrics['avg_first_sentence_length']:.0f}자 | — | {b['first_sentence_length_max']:.0f}자 |{sub_info}
"""

        return f"""당신은 아래 DATA 기사의 저자 본인입니다.
보도자료를 받으면, DATA 기사와 구별할 수 없는 ESG 기획기사를 작성하십시오.
DATA 기사를 정독하고 그 저자의 목소리에 완전히 몰입한 뒤 글을 쓰십시오.

---

# 1. DATA 기사 전문 — 당신이 쓴 기사입니다

아래 기사들을 정독하십시오. 이것이 당신의 글입니다.
새 기사를 쓸 때 이 기사들과 같은 문체, 같은 구조, 같은 톤, 같은 리듬으로 쓰십시오.

{examples_block}

---

# 2. 당신의 기사 구조 패턴 (구조적 청사진)

아래는 위 DATA 기사들에서 분석한 당신의 기사 구조 패턴입니다.
이것은 DATA 기사에서 관찰된 패턴의 기술이지, DATA 기사와 독립적인 규칙이 아닙니다.
아래 기술과 DATA 기사의 실물 사이에 괴리가 있으면, DATA 기사의 실물을 따르십시오.
새 기사를 쓸 때 이 구조를 참고하십시오.

{blueprint}

---

# 3. 당신의 표현 습관 (목소리 가이드)

아래는 위 DATA 기사들에서 관찰된 당신의 표현 습관입니다.
이것은 DATA 기사에서 관찰된 특성의 기술이지, DATA 기사와 독립적인 규칙이 아닙니다.
아래 기술과 DATA 기사의 실물 사이에 괴리가 있으면, DATA 기사의 실물을 따르십시오.
새 기사를 쓸 때 이 표현 습관을 참고하십시오.

{voice}

---

# 4. 기사의 목적

기업의 ESG 활동을 독자에게 알리고 긍정적으로 조명한다.
기업의 ESG 노력과 성과를 적극적으로 옹호하되, 과도한 아첨이나 광고 문구는 지양한다.
기자의 신뢰성 있는 시선으로 ESG 활동의 의미와 가치를 전달한다.
{metrics_block}
---

# 6. 보조 기술 지침

## 보도자료 처리
- 보도자료의 내용을 처음부터 끝까지 빠짐없이 기사에 반영한다.
- 보도자료에 기재되지 않은 내용은 절대 추가하지 않는다. (독자 반응 창작, 인물 동기 추측, 과장 금지)
- 보도자료의 순서를 그대로 따르지 않는다 — DATA 기사의 구조 패턴을 따른다.
- 보도자료의 수치, 고유명사, 수상 내역, 인용문은 원문 그대로 정확히 옮긴다.

## 한국일보 스타일북 준수 사항

### A. 문장 원칙
- 짧고 간결한 단문으로 써라. "가장 단순하게 쓰는 것이 가장 아름답게 쓰는 것이다."
- 한 문장에 한 가지 정보. 문장이 길어지면 독자의 관심을 잃는다.
- 주어와 술어 관계를 분명하게 써라. 주어가 실종된 문장을 쓰지 마라.
- 주어와 술어, 목적어와 서술어는 가까이 두라.
- 같은 형태의 종결어미를 단조롭게 반복하지 마라.
- 쓸데없는 종결어를 쓰지 마라. (매진된 상태이고→매진됐고, 소유권은 국방부가 갖고 있다→국방부에 있다)
- 축약어로 써라. (하였다→했다, 되었다→됐다, 문제이다→문제다)

### B. 금지 표현
- 이중피동 금지: 보여지다→보이다, 쓰여지다→쓰이다, 잊혀지다→잊히다
- 수동태 최소화: "~에 의해" → 주어+능동문. "이들에 의해 역사가 새로 쓰였다"→"이들이 역사를 새로 썼다"
- 물주구문(무생물 주어+타동사) → 부사어화 또는 능동문으로 전환
- 불필요한 '이/그/저' 지시어 삭제
- 접속사 남발 금지: '그리고' '그러나' '따라서' 등의 사용을 최소화하라.
- '-ㄹ 수 있다' 과용 회피
- 추측성 종결어 최소화: ~알려졌다, ~보인다, ~예상된다, ~전망이다 등은 꼭 필요한 경우만.
- '것'의 남발 금지: "위축될 수밖에 없는 것이다"→"없다"
- 접미사 '적' 남용 금지: "중심적 역할"→"중심 역할", "사실적으로 말하면"→"사실을 말하면"
- "~중에 있다" "~하고 있는 중이다" 금지 (진행형 중복): "빚을 갚아 나가고 있는 중이다"→"갚아 나가고 있다"
- "~화하다" 남발 금지: 동사나 형용사가 되는 말에는 붙이지 않는다. "비대화하다"→"비대하다"
- 기자가 먼저 흥분하지 마라: '~놀랄 만한 일이다' '대단하다' 등 감정적 표현 삼가.

### C. 쉬운 우리말
어려운 한자어 대신 쉬운 우리말을 써라:
- 결과를 초래할→가져올, 더욱 악화했다→나빠졌다, 개최→열다
- 규명하다→밝히다, 담합→짬짜미, 보유→가지고 있는
- 상이한→다른, 수뢰→돈 받은, 탈취하다→빼앗다
- 부과하다→매기다, 일소하다→없애다

### D. 숫자 표기
- 숫자는 아라비아 숫자로 쓰고 천 단위 앞에 반드시 쉼표. (1억3,500만원)
- 분수는 기사에서 "O분의 O"이라고 쓴다.
- '%'와 '%포인트'를 반드시 구분. (5%에서 8%로 → "3%포인트 증가")
- '배(倍)' 표현 주의: "2배 증가"(×)→"2배로 증가" 또는 "2배에 달했다"(○)
- 숫자가 너무 많이 들어가면 독자가 싫증낸다. 이유와 배경 분석이 더 낫다.
- 숙어·관용구의 숫자는 한글: 백만장자(○), 오십보백보(○)

### E. 호칭·이름
- 호칭은 '씨'가 원칙. 고교 미졸업자는 '군, 양'.
- 이름 뒤에 기관(회사), 직책 순: "이재용 삼성 부회장"
- 동일 범주 2인 이상 나열 시 마지막 사람 뒤에만 직함: "홍영표 나경원 심상정 의원"
- 전직은 '전' 띄어쓰기: "전두환 전 대통령"

### F. 시간·날짜
- 1주일의 시작은 월요일. 주말은 토·일.
- 오전/오후 표기 원칙. 낮 12시는 '정오'. 자정은 당일 0시.
- 과거나 미래가 분명한 연도에는 '지난'이나 '오는'을 붙이지 않는다.

### G. 인용 부호
- ' ': 주요 단어·어구 강조, 작품 내용 인용, 조어. 남발하면 문장이 난삽해진다.
- " ": 대화나 사람 말을 직접 인용할 때만 쓴다.
- " " 안의 마지막 문장에는 마침표를 쓰지 않는다: "조화를 상징한다"고 설명했다.

### H. 쉼표 규칙
- 한국인 이름 나열 시 쉼표 쓰지 않음: "이문열 황지우 조정래 최인호"
- 대등 관계 지명·국가 나열 시도 쉼표 없이: "일본 중국 대만 태국 등"
- 쉼표 역할을 하는 단어(특히, 그러나, 한편, 반면, 물론) 뒤에 쉼표 쓰지 마라.
- 한 문장에 쉼표가 많으면 리듬이 끊긴다. 남발하지 마라.

### I. 자주 틀리는 표현
- '입장'은 처지, 형편, 원칙, 견해, 방침 등으로 바꿔 써라.
- '유명세를 타다'(×)→'유명세를 치르다'(○), 부정적 맥락에서만 사용.
- '과반수 이상'(×)→'과반수' 또는 '절반 이상'.
- '성패 여부'(×, 겹말)→'성패' 또는 '성공 여부'.
- '장본인'은 나쁜 일의 주동자. 좋은 일에는 '주인공' '주역'.

## 형식
제목 → 부제(3줄 이상, DATA 기사 부제 형식 참조) → (빈 줄) → 본문
"""

    # ===================================================================
    # [1단계] 기획안 생성 — 핵심 테마 + 논리 전개도
    # ===================================================================

    def _create_outline(
        self,
        system_prompt: str,
        press_release: str,
        angle: str = "",
        temperature: float = 0.5,
        metrics: Optional[dict] = None,
    ) -> str:
        """
        보도자료를 분석하여 기획안(Theme & Outline)을 생성한다.

        출력물:
          1. 핵심 테마(Narrative Anchor): 기사 전체를 관통하는 한 문장
          2. 문단별 논리 전개도(Outline): 서론-본론-결론의 유기적 흐름

        핵심 제약:
          - 단순 병렬 나열(Cataloging)을 금지
          - 앞 문단의 결과가 뒷 문단의 원인이 되는 논리적 흐름을 구축
        """
        # 정량 참고 정보
        para_info = ""
        if metrics and metrics.get("bounds"):
            b = metrics["bounds"]
            para_info = f"""
참고 — DATA 기사의 정량 기준:
- 기사 총 길이: {b['article_length_min']:,.0f}~{b['article_length_max']:,.0f}자
- 문단 수: {b['paragraph_count_min']:.1f}~{b['paragraph_count_max']:.1f}개"""
            if metrics.get("avg_subheading_count", 0) > 0:
                para_info += f"\n- 중간제목: 약 {metrics['avg_subheading_count']:.1f}개"

        angle_block = ""
        if angle:
            angle_block = f"\n## 기사 방향(앵글)\n\n{angle}\n"

        outline_prompt = f"""당신은 시스템 프롬프트에 있는 DATA 기사의 저자입니다.
아래 보도자료로 ESG 기획기사를 쓰기 전에, 먼저 **기획안**을 작성하십시오.

## 보도자료

{press_release}
{angle_block}
## 기획안 작성 지침

### A. 핵심 테마(Narrative Anchor) 추출

보도자료 전체를 관통하는 **핵심 테마**를 한 문장으로 추출하십시오.
핵심 테마란, 보도자료에 등장하는 여러 사업·수치·사례를 하나의 서사로 꿰뚫는 상위 메시지입니다.

**핵심 테마는 반드시 보도자료에 실제로 등장하는 사실에 기반해야 합니다.**
보도자료에 없는 개념(ESG 경영, 문화 민주화, 사회적 가치, 접근성 개선 등)을 테마에 넣지 마십시오.

예시:
- (나쁜 예) "A기업이 ESG 경영을 통해 사회적 가치를 실현하고 있다"
  → 보도자료에 "ESG 경영"이라는 표현이 없다면 이것은 가공입니다.
- (좋은 예) "A기자의 쉬운 미술 스토리텔링이 6만 독자의 호응을 얻어 베스트셀러로 이어졌다"
  → 보도자료에 실제로 있는 사실(6만 구독자, 베스트셀러)로 구성됩니다.

### B. 보도자료 정보 단위 목록 (필수)

기획안을 작성하기 전에, 먼저 보도자료에 등장하는 **모든 정보 단위**를 빠짐없이 나열하십시오.
정보 단위란: 인명, 기관명, 사업명, 수치, 날짜, 수상 내역, 인용문, 도서 정보 등입니다.

[정보 단위 목록]
1. (정보1)
2. (정보2)
...

이 목록의 모든 항목이 논리 전개도의 어느 문단에 배치되는지 반드시 명시하십시오.
**목록에 있는데 어느 문단에도 배치되지 않은 정보가 있으면 안 됩니다.**

### C. 문단별 논리 전개도(Outline)

DATA 기사의 구조적 청사진을 참고하여, **서론-본론-결론** 형태의 문단별 전개도를 작성하십시오.

각 문단에 대해 다음을 기술하십시오:
- **문단 번호** (중간제목이 들어갈 위치도 표시)
- **문단의 역할** (도입/배경/핵심사례/수치근거/전환/전망/마무리 등)
- **담을 내용 요약** (보도자료의 어떤 정보를 배치하는가 — 정보 단위 번호로 명시)
- **이전 문단과의 연결 논리** (이 문단이 앞 문단의 어떤 성과·한계·질문에서 이어지는가)

### D. 절대 금지 사항

1. **단순 병렬 나열(Cataloging) 금지.**
   보도자료에 등장하는 사업을 순서대로 나열하는 것은 기획기사가 아닙니다.

2. **논리적 흐름 필수.**
   앞 문단의 결과가 뒷 문단의 원인이 되어야 합니다.
   문단과 문단 사이에 "왜 이 순서인가?"에 답할 수 있어야 합니다.

3. **보도자료에 없는 내용을 기획안에 절대 포함하지 마십시오.**
   다음은 구체적으로 금지되는 사례입니다:
   - 보도자료에 "ESG"라는 단어가 없으면 테마에 "ESG 경영"을 넣지 마십시오.
   - 보도자료에 "문화 민주화", "접근성 개선", "소외계층"이 없으면 넣지 마십시오.
   - 보도자료에 없는 독자 반응, 댓글, 감상을 기획안에 넣지 마십시오.
   - 보도자료에 없는 관계자 인터뷰를 기획안에 계획하지 마십시오.
   - 기획안의 모든 내용은 보도자료에서 직접 인용하거나 재구성한 것이어야 합니다.

4. **보도자료의 모든 정보를 배치하십시오.**
   정보 단위 목록에서 빠진 항목이 없어야 합니다.
   도서 가격, 쪽수, 목차 구성, 수상 내역, 화가 이름 등 구체적 정보를 누락하지 마십시오.
{para_info}

## 출력 형식

[핵심 테마]
(보도자료에 실제로 있는 사실만으로 구성된 한 문장)

[정보 단위 목록]
1. (정보1) → 문단 X에 배치
2. (정보2) → 문단 Y에 배치
...

[제목안]
(DATA 기사 제목 패턴을 따른 제목)

[부제안]
(3줄 이상, DATA 기사 부제 형식)

[논리 전개도]

서론:
  문단 1: [역할] — [내용 요약 + 정보 단위 번호] — [연결 논리: 기사의 출발점]
  문단 2: [역할] — [내용 요약 + 정보 단위 번호] — [연결 논리: 문단1에서 제기된 ...]

본론:
  (중간제목: ...)
  문단 3: [역할] — [내용 요약 + 정보 단위 번호] — [연결 논리: 문단2의 ...를 구체화]
  문단 4: [역할] — [내용 요약 + 정보 단위 번호] — [연결 논리: 문단3의 성과가 ...]
  ...

결론:
  문단 N: [역할] — [내용 요약 + 정보 단위 번호] — [연결 논리: 전체 논의를 ...]
"""

        response = self._api_call_with_retry(
            model=self.model_id,
            max_tokens=4096,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": outline_prompt}],
        )
        return self._extract_text(response)

    # ===================================================================
    # 메인 파이프라인
    # ===================================================================

    def generate(
        self,
        system_prompt: str,
        press_release: str,
        angle: str = "",
        temperature: float = 0.7,
        blueprint: str = "",
        voice: str = "",
        metrics: Optional[dict] = None,
        example_articles: Optional[list[dict]] = None,
        verbose: bool = True,
    ) -> dict:
        """6단계 파이프라인으로 기사를 생성한다."""
        has_verification = bool(blueprint or voice)
        total_steps = 6 if has_verification else 2

        # ---------------------------------------------------------------
        # [1단계] 기획안 생성 — 핵심 테마 + 논리 전개도
        # ---------------------------------------------------------------
        if verbose:
            print(f"  [1/{total_steps}] 기획안 생성 중 (핵심 테마 + 논리 전개도)...")

        start = time.time()
        outline = self._create_outline(
            system_prompt, press_release, angle,
            temperature=max(temperature - 0.2, 0.3),
            metrics=metrics,
        )
        elapsed = time.time() - start

        if verbose:
            print(f"    완료 ({elapsed:.1f}초)")
            # 핵심 테마만 발췌 출력
            for line in outline.split("\n"):
                if line.strip().startswith("[핵심 테마]"):
                    print(f"    {line.strip()}")
                elif "[핵심 테마]" in outline:
                    # 핵심 테마 다음 줄 출력
                    lines = outline.split("\n")
                    for i, ln in enumerate(lines):
                        if "[핵심 테마]" in ln and i + 1 < len(lines):
                            theme_line = lines[i + 1].strip()
                            if theme_line:
                                print(f"    → {theme_line}")
                            break
                    break

        # Rate limit 대기
        if verbose:
            print(f"    API rate limit 대기 (70초)...")
        time.sleep(70)

        # ---------------------------------------------------------------
        # [2단계] 초안 집필 — 기획안을 골격으로 집필
        # ---------------------------------------------------------------
        if verbose:
            print(f"  [2/{total_steps}] 초안 집필 중 (기획안 기반)...")

        user_prompt = self._build_generation_prompt(
            press_release, angle, metrics, outline=outline
        )

        start = time.time()
        response = self._api_call_with_retry(
            model=self.model_id,
            max_tokens=self.max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        draft = self._extract_text(response)
        elapsed = time.time() - start

        if verbose:
            print(f"    완료 ({elapsed:.1f}초, {response.usage.output_tokens}토큰)")

        # ---------------------------------------------------------------
        # [2-b단계] 초안 길이 부족 시 자동 확장 (최대 2회 재시도)
        # ---------------------------------------------------------------
        min_body_length = 2400
        max_body_length = 2700
        if metrics and metrics.get("bounds"):
            min_body_length = int(metrics["bounds"]["article_length_min"])
            max_body_length = int(metrics["bounds"]["article_length_max"])
        target_length = (min_body_length + max_body_length) // 2

        for expansion_attempt in range(2):
            body_length = self._measure_body_length(draft)
            if body_length >= min_body_length:
                break

            shortfall = min_body_length - body_length
            if verbose:
                print(f"    초안 길이 부족: {body_length}자 (목표 {min_body_length}~{max_body_length}자, {shortfall}자 부족)")
                print(f"    확장 재시도 {expansion_attempt + 1}/2...")
                print(f"    API rate limit 대기 (70초)...")
            time.sleep(70)

            expand_prompt = f"""아래 기사 초안이 너무 짧습니다. 보도자료에서 누락된 정보를 추가하여 확장하십시오.

현재 본문 길이: {body_length}자
목표 길이: {target_length}자 (허용 범위: {min_body_length}~{max_body_length}자)
부족한 분량: 약 {target_length - body_length}자

**주의: {max_body_length}자를 초과하지 마십시오. 목표는 정확히 {target_length}자 전후입니다.**

보도자료에서 아직 기사에 반영되지 않은 정보를 찾아 추가하십시오.
추가할 수 있는 정보: 도서 가격, 쪽수, 출판사명, 수상 내역, 선정 날짜, 화가 이름, 작품명, 목차 구성, 미술관 이름, 기자 경력, 인용문, 추천사 등.

기존 내용은 그대로 유지하면서 정보를 추가하십시오.
기존 문장을 삭제하지 마십시오.
보도자료에 없는 내용을 창작하지 마십시오.
문장은 짧게 쓰십시오 (목표: 문장당 60~69자).

## 현재 기사 초안

{draft}

## 보도자료 (여기서 누락된 정보를 찾으십시오)

{press_release}

확장된 기사 전문을 출력하십시오. 기사만 출력하고 다른 설명은 붙이지 마십시오.
"""
            expand_response = self._api_call_with_retry(
                model=self.model_id,
                max_tokens=self.max_tokens,
                temperature=max(temperature - 0.1, 0.3),
                system=system_prompt,
                messages=[{"role": "user", "content": expand_prompt}],
            )
            expanded = self._extract_text(expand_response)
            expanded_length = self._measure_body_length(expanded)

            if expanded_length > body_length:
                draft = expanded
                if verbose:
                    print(f"    확장 완료: {body_length}자 → {expanded_length}자")
            else:
                if verbose:
                    print(f"    확장 실패 (길이 증가 없음). 기존 초안 유지.")
                break

        result = {
            "outline": outline,
            "draft": draft,
            "final": draft,
            "style_check": "",
            "coverage_check": "",
            "metrics_check": "",
            "metrics_check_final": "",
            "refinement_notes": "",
        }

        if not has_verification:
            return result

        # Rate limit 대기
        if verbose:
            print(f"    API rate limit 대기 (70초)...")
        time.sleep(70)

        # ---------------------------------------------------------------
        # [3단계] DATA 대조 검증
        # ---------------------------------------------------------------
        if verbose:
            print(f"  [3/{total_steps}] DATA 대조 검증 중...")

        style_report = self._verify_against_data(
            draft, blueprint, voice, example_articles
        )
        result["style_check"] = style_report

        if verbose:
            print(f"    완료")

        # Rate limit 대기
        if verbose:
            print(f"    API rate limit 대기 (70초)...")
        time.sleep(70)

        # ---------------------------------------------------------------
        # [4단계] 보도자료 반영도 검증
        # ---------------------------------------------------------------
        if verbose:
            print(f"  [4/{total_steps}] 보도자료 반영도 검증 중...")

        coverage_report = self._verify_coverage(draft, press_release)
        result["coverage_check"] = coverage_report

        if verbose:
            print(f"    완료")

        # ---------------------------------------------------------------
        # [5단계] 정량 지표 검증
        # ---------------------------------------------------------------
        if verbose:
            print(f"  [5/{total_steps}] 정량 지표 검증 중...")

        metrics_report = self._verify_metrics(draft, metrics)
        result["metrics_check"] = metrics_report

        if verbose:
            for line in metrics_report.split("\n"):
                if "PASS" in line or "FAIL" in line:
                    print(f"    {line.strip()}")

        # Rate limit 대기
        if verbose:
            print(f"    API rate limit 대기 (70초)...")
        time.sleep(70)

        # ---------------------------------------------------------------
        # [6단계] 최종 교정
        # ---------------------------------------------------------------
        if verbose:
            print(f"  [6/{total_steps}] 최종 교정 중...")

        final, notes = self._final_revision(
            draft, press_release,
            style_report, coverage_report, metrics_report,
            system_prompt, temperature, metrics,
            example_articles,
        )

        # 안전장치: 교정 후 최소 길이 이하로 줄었으면 초안 유지
        # (단, 초안이 최대 길이를 초과했고 교정이 범위 안으로 줄인 경우는 허용)
        safe_min = 2400
        safe_max = 2700
        if metrics and metrics.get("bounds"):
            safe_min = int(metrics["bounds"]["article_length_min"])
            safe_max = int(metrics["bounds"]["article_length_max"])

        draft_len = self._measure_body_length(draft)
        final_len = self._measure_body_length(final)

        if final_len < draft_len and final_len < safe_min:
            # 교정이 최소 이하로 줄임 → 초안 유지
            if verbose:
                print(f"    교정 후 최소 미달 ({draft_len}→{final_len}자 < {safe_min}자). 초안 유지.")
            final = draft
            notes = "(교정 후 최소 미달로 초안 유지)"
        elif final_len < draft_len:
            # 교정이 줄였지만 최소 이상 → 허용 (특히 초안이 최대 초과였을 때)
            if verbose:
                print(f"    교정으로 길이 조정: {draft_len}→{final_len}자")

        result["final"] = final
        result["refinement_notes"] = notes

        if verbose:
            print(f"    완료")
            final_metrics = self._verify_metrics(final, metrics)
            result["metrics_check_final"] = final_metrics
            print(f"\n  [최종본 정량 검증]")
            for line in final_metrics.split("\n"):
                if "PASS" in line or "FAIL" in line:
                    print(f"    {line.strip()}")

        return result

    def generate_stream(
        self,
        system_prompt: str,
        press_release: str,
        angle: str = "",
        temperature: float = 0.7,
    ) -> Generator[str, None, None]:
        """스트리밍 방식으로 초안을 생성한다."""
        user_prompt = self._build_generation_prompt(press_release, angle)
        with self.client.messages.stream(
            model=self.model_id,
            max_tokens=self.max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for text in stream.text_stream:
                yield text

    # ===================================================================
    # [3단계] DATA 대조 검증
    # ===================================================================

    def _verify_against_data(
        self,
        article: str,
        blueprint: str,
        voice: str,
        example_articles: Optional[list[dict]] = None,
    ) -> str:
        """초안을 DATA 기사와 직접 비교하여 검증한다."""

        # DATA 기사 일부를 직접 포함 (비교 대상)
        data_excerpts = ""
        if example_articles:
            excerpts = []
            for art in example_articles[:2]:
                lines = [ln.strip() for ln in art["text"].split("\n") if ln.strip()]
                intro = "\n".join(lines[:min(8, len(lines))])
                outro = "\n".join(lines[max(0, len(lines)-5):])
                excerpts.append(
                    f"[{art['title']}]\n도입부:\n{intro}\n\n마무리부:\n{outro}"
                )
            data_excerpts = "\n\n---\n\n".join(excerpts)

        prompt = f"""당신은 기사 편집자입니다. 아래 '검증 대상 기사'가 'DATA 기사'와 동일한 저자가 쓴 것처럼 읽히는지 검증하십시오.

## 검증의 핵심 원칙

이 검증의 유일한 기준은 **"이 기사가 DATA 저자가 직접 쓴 것처럼 읽히는가?"**입니다.
추상적 문체 규칙이나 분석 프레임워크의 항목을 기계적으로 점검하는 것이 아닙니다.
DATA 기사의 실물과 검증 대상 기사를 직접 대조하여, 동일 저자의 글로 느껴지는지를 판단하십시오.

## DATA 기사의 구조 패턴 (구조적 청사진)

{blueprint[:3000]}

## DATA 기사의 표현 습관 (목소리 가이드)

{voice[:2000]}

## DATA 기사 실물 발췌 (직접 비교용)

{data_excerpts}

## 검증 대상 기사

{article}

## 검증 기준

이 기사를 DATA 기사와 **직접 비교**하여 다음을 판단하십시오.
아래 항목은 DATA 기사와의 유사도를 측정하기 위한 관점이지, 독립적 규칙 점검 항목이 아닙니다.

### A. 구조적 유사도 (DATA 구조 패턴과 비교)
1. 도입부가 DATA 기사의 도입부 패턴을 따르는가?
2. 전개부의 문단 배치가 DATA 기사의 패턴을 따르는가?
3. 마무리부가 DATA 기사의 마무리 패턴을 따르는가?
4. 중간제목의 배치와 형식이 DATA와 유사한가?
5. 부제가 DATA 기사의 부제 형식과 유사한가?

### B. 문체적 유사도 (DATA 기사와 직접 비교)
1. 문장 리듬(단문-복문 교차)이 DATA 기사와 유사한가?
2. 종결 어미 패턴이 DATA 기사와 유사한가?
3. 어휘 수준이 DATA 기사와 유사한가?
4. 톤과 온도가 DATA 기사와 유사한가?
5. DATA 저자의 특징적 표현이 재현되었는가?

### C. 논리적 흐름 검증
1. 기사 전체를 관통하는 핵심 테마가 있는가?
2. 문단 간 전환이 논리적 이음새로 연결되는가, 아니면 독립된 토막으로 나열되는가?
3. 단순 병렬 나열(Cataloging) 구간이 있는가?

### D. 기술적 오류 (한국일보 스타일북 기준)
1. 번역투: 이중피동(보여지다/쓰여지다), "-에 의해", 물주구문, 수동태 과용
2. LLM 패턴: 접속 부사 기계적 삽입, '-ㄹ 수 있다' 과용, AI 어시스턴트의 교시적 말투
3. 종결어 문제: 같은 종결어미 반복, 불필요한 종결어("~된 상태이고", "~갖고 있다")
4. 남용 표현: 접미사 '적' 남용, '것'의 남발, "~중에 있다" 진행형 중복, "~화하다" 남발
5. 한자어 과용: 쉬운 우리말로 대체 가능한 한자어가 있는가?
6. 숫자 표기: 천 단위 쉼표, '%'와 '%포인트' 구분, 배수 표현 정확성
7. 인용 부호: ' '와 " " 구분, " " 안 마침표 규칙, 인용부호 남발 여부
8. 감정적 표현: '놀랄 만한' '대단하다' 등 기자의 감정 개입

---

각 항목에 대해 [적합/부적합]과 구체적 근거(해당 문장 인용)를 제시하십시오.
판단의 기준은 항상 "DATA 기사의 저자가 이렇게 쓸 것인가?"입니다.
추상적 규칙 위반 여부가 아니라, DATA 기사의 실물과의 차이를 지적하십시오.

마지막에 다음을 작성하십시오:

[종합 판정] DATA 기사와의 유사도를 1~10점으로 평가 (10점: 동일 저자가 쓴 것 같음)
[핵심 수정 사항] DATA 기사에 더 가까워지기 위해 수정해야 할 사항 (우선순위 순, 각 항목에 DATA 기사의 해당 부분을 인용하여 비교)
"""
        response = self._api_call_with_retry(
            model=self.model_id,
            max_tokens=4096,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._extract_text(response)

    # ===================================================================
    # [4단계] 보도자료 반영도 검증
    # ===================================================================

    def _verify_coverage(self, article: str, press_release: str) -> str:
        """보도자료 반영도를 검증한다."""
        prompt = f"""당신은 팩트체크 전문 편집자입니다.

## 원본 보도자료

{press_release}

## 검증 대상 기사

{article}

## 검증 지시

### A. 반영도 검증 (보도자료 → 기사)
보도자료의 내용을 문단 단위로 검토하십시오.
각 정보 단위(사실, 수치, 인용문, 프로그램명, 인명, 지명, 일정 등)에 대해:
- [반영됨] 기사에 포함
- [누락됨] 기사에서 누락
- [변형됨] 원본과 다르게 서술

### B. 가공 검증 (기사 → 보도자료)
기사에 보도자료 원문에 없는 정보가 있는지 확인하십시오.
- [원문 근거 없음] 보도자료에 없는 내용이 추가된 경우

### C. 종합 판정
[반영도 점수] X/10
[가공 여부] 있음/없음
[수정 필요 사항] 구체적 수정 지시 목록
"""
        response = self._api_call_with_retry(
            model=self.model_id,
            max_tokens=4096,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._extract_text(response)

    # ===================================================================
    # [5단계] 정량 지표 검증
    # ===================================================================

    def _verify_metrics(self, article: str, metrics: Optional[dict]) -> str:
        """정량 지표를 DATA 기준과 비교한다."""
        if not metrics or not metrics.get("bounds"):
            return "정량 지표 기준이 없어 검증을 생략합니다."

        raw_lines = [ln.strip() for ln in article.strip().split('\n') if ln.strip()]

        # 제목/부제 건너뛰기
        body_start = 0
        for i, ln in enumerate(raw_lines):
            if len(ln) >= 100 or i >= 5:
                body_start = i
                break
        body_lines = raw_lines[body_start:]

        # 중간제목 감지 + 문단 분리
        subheadings = []
        body_paragraphs = []
        current_para = []

        for ln in body_lines:
            is_subheading = (
                len(ln) <= 50
                and not ln.endswith('.')
                and not ln.endswith('다.')
                and not ln.endswith('다')
                and not ln.endswith('"')
                and not ln.endswith("'")
                and len(ln) >= 4
            )
            if is_subheading and current_para:
                body_paragraphs.append(' '.join(current_para))
                current_para = []
                subheadings.append(ln)
            elif len(ln) >= 60:
                current_para.append(ln)
            elif current_para:
                current_para.append(ln)
            elif not is_subheading:
                current_para.append(ln)

        if current_para:
            body_paragraphs.append(' '.join(current_para))
        if not body_paragraphs:
            body_paragraphs = [' '.join(body_lines)]

        # 문장 분리
        all_sentences = []
        first_sentences = []
        for para in body_paragraphs:
            sentences = self._split_sentences_simple(para)
            all_sentences.extend(sentences)
            if sentences:
                first_sentences.append(sentences[0])

        # 측정
        actual_length = sum(len(p) for p in body_paragraphs)
        actual_para_count = len(body_paragraphs)
        actual_avg_para_len = round(actual_length / max(actual_para_count, 1), 1)
        actual_avg_sent_len = round(
            sum(len(s) for s in all_sentences) / max(len(all_sentences), 1), 1
        )
        actual_avg_first_sent_len = round(
            sum(len(s) for s in first_sentences) / max(len(first_sentences), 1), 1
        )

        b = metrics["bounds"]
        lines = ["=== 정량 지표 검증 (DATA 기준 대비) ===\n"]

        checks = [
            {"name": "기사 총 길이", "actual": actual_length, "target": metrics["avg_article_length"],
             "min": b["article_length_min"], "max": b["article_length_max"], "unit": "자"},
            {"name": "문단 수", "actual": actual_para_count, "target": metrics["avg_paragraph_count"],
             "min": b["paragraph_count_min"], "max": b["paragraph_count_max"], "unit": "개"},
            {"name": "문단 평균 길이", "actual": actual_avg_para_len, "target": metrics["avg_paragraph_length"],
             "min": b["paragraph_length_min"], "max": b["paragraph_length_max"], "unit": "자"},
            {"name": "문장 평균 길이", "actual": actual_avg_sent_len, "target": metrics["avg_sentence_length"],
             "min": b["sentence_length_min"], "max": b["sentence_length_max"], "unit": "자"},
        ]

        all_pass = True
        for c in checks:
            passed = c["min"] <= c["actual"] <= c["max"]
            status = "[PASS]" if passed else "[FAIL]"
            if not passed:
                all_pass = False
            diff_pct = ((c["actual"] - c["target"]) / c["target"] * 100) if c["target"] else 0
            sign = "+" if diff_pct >= 0 else ""
            lines.append(
                f"{status} {c['name']}: 현재 {c['actual']:,.1f}{c['unit']} / "
                f"DATA 평균 {c['target']:,.1f}{c['unit']} ({sign}{diff_pct:.1f}%) / "
                f"허용 {c['min']:,.1f}~{c['max']:,.1f}{c['unit']}"
            )

        first_sent_max = b.get("first_sentence_length_max", 999)
        first_sent_passed = actual_avg_first_sent_len <= first_sent_max
        if not first_sent_passed:
            all_pass = False
        lines.append(
            f"{'[PASS]' if first_sent_passed else '[FAIL]'} 문단 첫 문장 평균: "
            f"현재 {actual_avg_first_sent_len:.0f}자 / "
            f"DATA 평균 {metrics.get('avg_first_sentence_length', 0):.0f}자 / "
            f"상한 {first_sent_max:.0f}자"
        )

        target_sub = metrics.get("avg_subheading_count", 0)
        if target_sub > 0 or len(subheadings) > 0:
            lines.append(
                f"[INFO] 중간제목: 현재 {len(subheadings)}개 / DATA 평균 {target_sub:.1f}개"
            )
            for sh in subheadings:
                lines.append(f"  └ \"{sh}\"")

        # 긴 첫 문장 지적
        long_first = [(i+1, len(fs), fs[:60]) for i, fs in enumerate(first_sentences) if len(fs) > first_sent_max]
        if long_first:
            lines.append(f"\n[경고] 첫 문장이 너무 긴 문단:")
            for pn, length, preview in long_first:
                lines.append(f"  문단 {pn}: {length}자 — \"{preview}...\"")

        lines.append("")
        if all_pass:
            lines.append("[종합] 모든 지표가 DATA 허용 범위 이내.")
        else:
            lines.append("[종합] 일부 지표가 DATA 범위를 벗어남. 교정 필요.")
            lines.append("")
            lines.append("[수정 지시]")
            for c in checks:
                if not (c["min"] <= c["actual"] <= c["max"]):
                    direction = "늘리" if c["actual"] < c["min"] else "줄이"
                    target = c["min"] if c["actual"] < c["min"] else c["max"]
                    lines.append(f"  - {c['name']}: {c['actual']:,.1f} → {target:,.1f}{c['unit']} 이내로 {direction}십시오.")
            if not first_sent_passed:
                lines.append(f"  - 문단 첫 문장: {actual_avg_first_sent_len:.0f}자 → {first_sent_max:.0f}자 이하로 줄이십시오.")

        return "\n".join(lines)

    @staticmethod
    def _split_sentences_simple(text: str) -> list[str]:
        parts = re.split(r'(?<=[다요음임함됨][\.\?!])\s+', text.strip())
        result = []
        for part in parts:
            sub = re.split(r'(?<=다\.)\s+|(?<=요\.)\s+', part)
            result.extend(sub)
        return [s.strip() for s in result if s.strip() and len(s.strip()) >= 5]

    # ===================================================================
    # [6단계] 최종 교정
    # ===================================================================

    def _final_revision(
        self,
        draft: str,
        press_release: str,
        style_report: str,
        coverage_report: str,
        metrics_report: str,
        system_prompt: str,
        temperature: float,
        metrics: Optional[dict] = None,
        example_articles: Optional[list[dict]] = None,
    ) -> tuple[str, str]:
        """검증 보고서를 반영하여 최종 교정한다. DATA 기사를 직접 참조."""

        # DATA 기사 도입부/마무리부 발췌 (교정 시 직접 참조)
        data_reference = ""
        if example_articles:
            refs = []
            for art in example_articles[:2]:
                lines = [ln.strip() for ln in art["text"].split("\n") if ln.strip()]
                intro = "\n".join(lines[:min(6, len(lines))])
                outro = "\n".join(lines[max(0, len(lines)-4):])
                refs.append(f"[{art['title']}]\n도입: {intro}\n마무리: {outro}")
            data_reference = "\n\n".join(refs)

        # 정량 기준 블록
        metrics_instruction = ""
        if metrics and metrics.get("bounds"):
            b = metrics["bounds"]
            sent_block = ""
            if b.get("sentence_length_max"):
                sent_block = f"- 문장 평균 길이: {b['sentence_length_min']:.0f}~{b['sentence_length_max']:.0f}자\n- 문단 첫 문장: {b.get('first_sentence_length_max', 60):.0f}자 이하"
            metrics_instruction = f"""
## 정량 기준 (DATA ±5%)
- 기사 본문 총 길이: {b['article_length_min']:,.0f}~{b['article_length_max']:,.0f}자
- 문단 수: {b['paragraph_count_min']:.1f}~{b['paragraph_count_max']:.1f}개
- 문단 평균 길이: {b['paragraph_length_min']:,.0f}~{b['paragraph_length_max']:,.0f}자
{sent_block}
"""

        revision_prompt = f"""아래 기사 초안을 검증 보고서에 따라 교정하십시오.

교정의 최우선 목표: **DATA 기사의 저자가 쓴 것처럼 읽히게 만들기**.
이것은 추상적 규칙이나 분석 프레임워크의 체크리스트를 충족시키는 작업이 아닙니다.
DATA 기사를 직접 떠올리면서, 그 저자가 쓴 것과 구별할 수 없는 글로 만드는 것이 목표입니다.
검증 보고서의 지적 사항을 반영하되, 항상 DATA 기사에 더 가까워지는 방향으로 수정하십시오.

## 기사 초안

{draft}

## 원본 보도자료

{press_release}

## DATA 기사 참조 (도입부/마무리부 발췌)

{data_reference}

## DATA 대조 검증 보고서

{style_report}

## 보도자료 반영도 검증 보고서

{coverage_report}

## 정량 지표 검증 보고서

{metrics_report}
{metrics_instruction}

## 교정 우선순위

1. **DATA 유사도 향상**: DATA 대조 검증에서 지적된 사항을 최우선으로 수정
   - 구조가 DATA 패턴과 다르면 재배치
   - 문체가 DATA와 다르면 DATA의 문장 리듬·종결 어미·어휘로 교체
   - AI 어시스턴트 말투가 섞였으면 DATA 저자의 어조로 교체
2. **논리적 흐름 강화**: 단순 나열 구간이 있으면 논리적 이음새를 삽입하여 재구성
3. **스타일북 준수**: 이중피동·수동태→능동문, 접속사 남발 제거, 같은 종결어미 반복 제거, 접미사 '적' 남용 제거, 쉬운 우리말로 대체, 숫자 표기법(천 단위 쉼표, %포인트 구분), 인용부호 규칙(' '와 " " 구분), 감정적 표현 자제
4. **반영도 교정**: [누락됨]은 추가, [원문 근거 없음]은 삭제, [변형됨]은 원문에 맞게 수정
5. **정량 교정**: [FAIL] 항목을 DATA 범위 안으로 조정
6. **형식**: 부제 3줄 이상, 중간제목 DATA 패턴 준수

## 기사 길이 교정 — 절대 규칙

**교정 후 기사가 초안보다 짧아지는 것을 금지합니다.**
정량 검증에서 기사 총 길이가 DATA 범위보다 짧다면:
- [원문 근거 없음] 삭제로 줄어든 분량을 [누락됨] 정보 추가로 반드시 보충하십시오.
- 보도자료에서 아직 반영하지 않은 정보(수상 내역, 구체적 수치, 사업명, 인명 등)를 찾아 추가하십시오.
- 문장을 단축하되 문단과 정보량은 늘리십시오.
- 최종 기사는 반드시 정량 기준의 허용 최소 길이 이상이어야 합니다.

아래 형식으로 출력:

[수정 사항 요약]
(수정 내용 간략 나열)

[최종 기사]
(수정 완료된 기사 전문)
"""
        # 교정 전용 간결한 시스템 프롬프트 (전체 시스템 프롬프트를 보내면 토큰 초과)
        min_len = 2400
        max_len = 2700
        if metrics and metrics.get("bounds"):
            min_len = int(metrics["bounds"]["article_length_min"])
            max_len = int(metrics["bounds"]["article_length_max"])

        revision_system = f"""당신은 ESG 기획기사 전문 편집자입니다.
검증 보고서에 따라 기사를 교정하십시오.
교정의 유일한 기준: "DATA 기사의 저자가 쓴 것처럼 읽히는가?"
스타일북 규칙: 이중피동·수동태 금지, 접속사 남발 금지, 같은 종결어미 반복 금지, 쉬운 우리말 사용, 숫자 천 단위 쉼표, 감정적 표현 자제.
가공 금지: 보도자료에 없는 내용을 추가하지 마십시오.
길이 규칙: 교정 후 본문은 {min_len}~{max_len}자 범위 안이어야 합니다. 초과하면 덜 중요한 세부 정보를 줄이십시오.
문장 규칙: 한 문장은 최대 69자. 긴 문장은 두 문장으로 나누십시오. 문단 첫 문장은 68자 이하."""

        response = self._api_call_with_retry(
            model=self.model_id,
            max_tokens=self.max_tokens,
            temperature=max(temperature - 0.1, 0.3),
            system=revision_system,
            messages=[{"role": "user", "content": revision_prompt}],
        )

        full_text = self._extract_text(response)

        if "[최종 기사]" in full_text:
            parts = full_text.split("[최종 기사]", 1)
            notes = parts[0].replace("[수정 사항 요약]", "").strip()
            final = parts[1].strip()
        else:
            notes = ""
            final = full_text

        return final, notes

    # ===================================================================
    # 앵글 제안
    # ===================================================================

    def suggest_angles(
        self,
        press_release: str,
        blueprint: str,
        voice: str,
        n_angles: int = 3,
    ) -> str:
        """보도자료에 대한 기획기사 앵글을 제안한다."""
        prompt = f"""당신은 아래 문체 특성을 가진 ESG 기획기사 기자입니다.
이 기자의 시선으로 보도자료를 읽고, 기획기사 앵글을 {n_angles}개 제안하십시오.

각 앵글에 대해:
- 제목(안)
- 부제(안) 3줄
- 핵심 논점 (한 문장)

기업의 ESG 활동을 긍정적으로 조명하되 과도한 아첨은 피하십시오.
보도자료에 없는 사실을 앵글에 포함하지 마십시오.

## 기자의 표현 습관
{voice[:2000]}

## 기자의 기사 구조 패턴
{blueprint[:2000]}

## 보도자료
{press_release}
"""
        response = self._api_call_with_retry(
            model=self.model_id,
            max_tokens=3000,
            temperature=0.8,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._extract_text(response)

    # ===================================================================
    # 피드백 반영 재생성
    # ===================================================================

    def regenerate_with_feedback(
        self,
        system_prompt: str,
        press_release: str,
        previous_article: str,
        feedback: str,
        temperature: float = 0.7,
    ) -> str:
        """피드백을 반영하여 재생성한다."""
        messages = [
            {"role": "user", "content": self._build_generation_prompt(press_release)},
            {"role": "assistant", "content": previous_article},
            {
                "role": "user",
                "content": (
                    f"위 기사에 대한 수정 요청:\n\n{feedback}\n\n"
                    "이 피드백을 반영하여 기사를 처음부터 다시 작성하십시오.\n"
                    "DATA 기사 저자의 목소리와 구조를 그대로 유지하십시오.\n"
                    "보도자료에 없는 내용은 추가하지 마십시오.\n"
                    "부제 3줄 이상 포함하십시오."
                ),
            },
        ]
        response = self._api_call_with_retry(
            model=self.model_id,
            max_tokens=self.max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        )
        return self._extract_text(response)

    # ===================================================================
    # 내부 유틸리티
    # ===================================================================

    def _build_generation_prompt(
        self,
        press_release: str,
        angle: str = "",
        metrics: Optional[dict] = None,
        outline: str = "",
    ) -> str:
        """기사 생성 사용자 프롬프트를 구축한다."""

        metrics_instruction = ""
        if metrics and metrics.get("bounds"):
            b = metrics["bounds"]
            sent_block = ""
            if b.get("sentence_length_max"):
                sent_block = f"   - 문장 평균 길이: {b['sentence_length_min']:.0f}~{b['sentence_length_max']:.0f}자\n   - 문단 첫 문장: {b.get('first_sentence_length_max', 60):.0f}자 이하"

            sub_block = ""
            if metrics.get("avg_subheading_count", 0) > 0:
                sub_block = f"""
6. **중간제목은 DATA 기사 패턴을 따르십시오.**
   DATA 기사에 평균 {metrics['avg_subheading_count']:.1f}개의 중간제목이 있습니다.
   약 {metrics.get('avg_paras_per_subheading', 2.5):.1f}문단마다 배치합니다."""

            metrics_instruction = f"""
5. **정량 기준 (DATA ±5%):**
   - 기사 본문 총 길이: {b['article_length_min']:,.0f}~{b['article_length_max']:,.0f}자
   - 문단 수: {b['paragraph_count_min']:.1f}~{b['paragraph_count_max']:.1f}개
   - 문단 평균 길이: {b['paragraph_length_min']:,.0f}~{b['paragraph_length_max']:,.0f}자
   {sent_block}
{sub_block}"""

        # 기획안 블록 (v4.1 핵심 변경: outline이 주어지면 이를 골격으로 집필)
        min_length = 2400  # 기본 최소 길이
        max_length = 2700  # 기본 최대 길이
        if metrics and metrics.get("bounds"):
            min_length = int(metrics["bounds"]["article_length_min"])
            max_length = int(metrics["bounds"]["article_length_max"])

        outline_block = ""
        if outline:
            outline_block = f"""
## 기획안 (Theme & Outline) — 이 골격을 따라 집필하십시오

아래는 보도자료를 분석하여 사전에 작성된 기획안입니다.
이 기획안의 핵심 테마와 논리 전개도를 기사의 뼈대로 삼으십시오.
기획안에 명시된 문단 간 연결 논리를 반드시 기사에 반영하십시오.

{outline}

---
"""

        prompt = f"""아래 보도자료로 ESG 기획기사를 작성하십시오.

## 보도자료

{press_release}
{outline_block}
## 작성 지침

당신은 시스템 프롬프트에 있는 DATA 기사의 저자입니다.
DATA 기사를 다시 한 번 떠올리고, 그 기사들과 동일한 수준의 기획기사를 작성하십시오.

1. **기획안의 논리 전개도를 따르십시오.**
   위에 제시된 기획안의 핵심 테마(Narrative Anchor)가 기사 전체를 관통해야 합니다.
   기획안의 문단별 전개도에 명시된 순서·역할·연결 논리를 충실히 따르십시오.
   기획안에 없는 구조로 임의 재배치하지 마십시오.

2. **DATA 기사의 문체를 재현하십시오.**
   DATA 기사에서 관찰되는 문장 리듬, 종결 어미, 어휘 수준, 톤을 그대로 쓰십시오.
   표현 은행에 수집된 표현들을 자연스럽게 활용하십시오.

3. **보도자료의 모든 내용을 빠짐없이 반영하십시오.**
   기획안의 [정보 단위 목록]에 있는 모든 항목을 기사에 포함하십시오.
   보도자료에 없는 내용은 절대 추가하지 마십시오. 구체적으로:
   - 보도자료에 없는 독자 반응, 감상, 댓글을 창작하지 마십시오.
   - 보도자료에 없는 관계자·전문가 인터뷰를 창작하지 마십시오.
   - 보도자료에 "ESG"라는 단어가 없으면 기사에 "ESG 경영"을 넣지 마십시오.
   - 보도자료에 없는 "문화 민주화", "접근성 개선", "소외계층" 같은 개념을 넣지 마십시오.
   - 보도자료에 없는 인물의 동기, 신념, 감정을 추측하여 서술하지 마십시오.
   - 보도자료에 "요청에 힘입어"라고 적혀 있으면 "빗발쳤다"로 과장하지 마십시오.
   - 보도자료의 수치, 고유명사, 수상 내역, 도서 가격, 쪽수는 정확히 옮기십시오.

4. **데이터 과포화 방지 및 논리적 전환 강제:**
   - 수치 및 데이터의 무비판적 나열을 엄격히 금지합니다.
     한 문단에 등장하는 정량적 수치는 **최대 2개**로 제한하며,
     반드시 그 수치가 핵심 테마에 기여하는 '의미'를 함께 서술하십시오.
   - 문단과 문단이 전환될 때, 독립된 주제로 갑자기 넘어가는 것을 금지합니다.
     이전 문단의 성과나 한계가 다음 문단 사업의 배경이 되는 식의
     **논리적 이음새(담화 표지)**를 반드시 포함하십시오.
{metrics_instruction}

**기사 본문 길이 규칙**: 본문(제목·부제 제외)은 반드시 **{min_length}자 이상 {max_length}자 이하**로 작성하십시오. 부족하면 보도자료에서 누락된 정보를 추가하고, 초과하면 덜 중요한 세부 정보를 줄이십시오.

**문장 길이 규칙**: 한 문장은 **최대 69자**입니다. 긴 문장은 두 문장으로 나누십시오. 특히 문단의 첫 문장은 **68자 이하**로 쓰십시오.

**형식**: 제목 → 부제(3줄 이상, DATA 기사 부제 형식) → (빈 줄) → 본문

**기술적 주의**: 시스템 프롬프트의 '한국일보 스타일북 준수 사항'을 반드시 따르십시오. 특히: 이중피동·수동태 금지, 접속사 남발 금지, 쉬운 우리말 사용, 숫자 표기법(천 단위 쉼표, %와 %포인트 구분), 인용 부호 규칙, 감정적 표현 자제.
"""
        if angle and not outline:
            # outline이 이미 angle을 반영하고 있으므로, outline 없을 때만 별도 추가
            prompt += f"\n## 기사 방향(앵글)\n\n{angle}\n\n이 방향으로 작성하십시오.\n"

        return prompt

    @staticmethod
    def _measure_body_length(article: str) -> int:
        """기사 본문 길이를 측정한다 (제목·부제 제외)."""
        raw_lines = [ln.strip() for ln in article.strip().split('\n') if ln.strip()]
        # 제목/부제 건너뛰기: 첫 번째 긴 줄(>=100자) 또는 5번째 줄부터 본문
        body_start = 0
        for i, ln in enumerate(raw_lines):
            if len(ln) >= 100 or i >= 5:
                body_start = i
                break
        body_lines = raw_lines[body_start:]
        return sum(len(ln) for ln in body_lines)

    @staticmethod
    def _extract_text(response) -> str:
        return "".join(
            block.text for block in response.content if block.type == "text"
        )
