"""
style_dna.py (v4.0)
===================
DATA 기사 저자의 문체를 재현 가능한 형태로 추출하는 모듈.

이전 버전과의 근본적 차이:
  - v2~v3: 12축 분석 프레임워크로 추상적 문체 서술을 도출
    → LLM은 추상적 서술을 읽고도 자기 고유 패턴으로 회귀
  - v4: 구체적 재현 가이드를 도출
    → 구조적 청사진(paragraph-by-paragraph flow template)
    → 표현 은행(실제 문장/구문 수집)
    → 간결한 목소리 가이드(추상적 분석이 아닌 실전 지침)

추출 단계:
  Phase 1: 구조적 청사진 + 표현 은행 (실천적·구체적)
  Phase 2: 목소리 프로필 (간결·실전적)
  Phase 3: 정량 지표 (로컬 계산)
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import anthropic


# ---------------------------------------------------------------------------
# Phase 1: 구조적 청사진 + 표현 은행 추출 프롬프트
# ---------------------------------------------------------------------------

BLUEPRINT_SYSTEM_PROMPT = """당신은 편집 전문가이자 기사 구조 분석가입니다.
주어진 기사들의 **구체적인 구조와 표현 패턴**을 분석하여,
동일한 저자가 새 기사를 쓸 때 그대로 따를 수 있는 **실전 재현 가이드**를 만드는 것이 목표입니다.

추상적인 문체론적 분석이 아니라, 구체적이고 실행 가능한 지침을 도출하십시오.
"이 저자는 ~한 경향이 있다"가 아니라 "1문단은 ~로 시작하고 ~로 끝난다"와 같은 수준입니다."""

BLUEPRINT_USER_PROMPT_TEMPLATE = """아래는 한 저자가 작성한 연작 기획기사 {n}편입니다.
이 기사들의 구조와 표현 패턴을 분석하여 재현 가이드를 작성하십시오.

---

## 분석 대상 기사

{articles_block}

---

## 요청 사항

### 1. 구조적 청사진 (Structural Blueprint)

각 기사의 구조를 문단 단위로 매핑한 뒤, 기사들에서 공통적으로 나타나는 **전형적 구조 패턴**을 도출하십시오.

#### 1-1. 개별 기사 구조 매핑
각 기사에 대해 문단별로 다음을 기록하십시오:
- 문단 번호
- 문단의 역할 (도입/장면설정/배경설명/핵심정보전달/구체사례/인용/수치제시/전환/요약/전망/마무리 등)
- 해당 문단의 첫 문장 (실제 인용)
- 대략적 길이 (짧은/보통/긴)

#### 1-2. 공통 구조 템플릿
개별 매핑 결과를 종합하여, 이 저자의 기사가 따르는 **전형적 흐름**을 도식화하십시오:

```
[도입부] (N문단)
 └ 문단 1: [역할] — [패턴 설명]
 └ 문단 2: [역할] — [패턴 설명]

[전개부] (N문단)
 └ 문단 3~4: [역할] — [패턴 설명]
 └ 중간제목
 └ 문단 5~7: [역할] — [패턴 설명]
 ...

[마무리부] (N문단)
 └ 문단 N-1: [역할] — [패턴 설명]
 └ 문단 N: [역할] — [패턴 설명]
```

#### 1-3. 제목·부제·중간제목 패턴
- **제목 작법**: 실제 제목들을 나열하고 공통 패턴을 추출 (길이, 구조, 키워드 배치)
- **부제 작법**: 실제 부제들을 나열하고 패턴 추출 (줄 수, 각 줄의 역할, 문장 구조)
- **중간제목 작법**: 실제 중간제목들을 나열하고 패턴 추출 (배치 간격, 형식, 길이)

#### 1-4. 도입부 패턴 상세
- 첫 문장은 어떻게 시작하는가? (실제 첫 문장 5개 이상 인용)
- 도입부에서 어떤 정보를 어떤 순서로 제시하는가?
- 독자의 관심을 어떻게 끄는가?

#### 1-5. 마무리부 패턴 상세
- 마지막 문단은 어떻게 끝나는가? (실제 마지막 문장 5개 이상 인용)
- 기사의 결론을 어떻게 맺는가? (전망 제시? 의미 부여? 기대감? 요약?)
- 도입부와의 수미상관 여부

### 2. 표현 은행 (Expression Bank)

이 저자가 **반복적으로 사용하는 구체적 표현**을 수집하십시오. 실제 기사에서 직접 인용하십시오.

#### 2-1. 문단 시작 표현 (각 위치별)
- 기사 첫 문장으로 자주 쓰는 패턴 (실제 문장 인용)
- 새 문단을 시작할 때 자주 쓰는 표현 (실제 문장 인용)
- 중간제목 직후 문단을 시작하는 표현

#### 2-2. 전환 표현
- 문단 간 전환에 사용하는 표현 (접속사/부사/구문)
- 주제를 바꿀 때 사용하는 표현
- 구체적 사례로 넘어갈 때 사용하는 표현

#### 2-3. 강조·평가 표현
- 긍정적 평가를 할 때 사용하는 표현
- ESG 활동의 의미를 부여할 때 사용하는 표현
- 수치/성과를 제시할 때 사용하는 프레이밍

#### 2-4. 마무리 표현
- 기사를 마무리할 때 자주 쓰는 문장 패턴 (실제 인용)
- 기대감/전망을 표현하는 방식

#### 2-5. 특징적 어휘·구문
- 이 저자만의 습관적 표현 (반복 등장하는 부사, 조사 사용 패턴, 관용 구문)
- 자주 사용하는 종결 어미 패턴 (실제 문장 끝 10개 이상 인용)
- 자주 사용하는 문장 부호 패턴

### 3. 문단 내부 구성 패턴

#### 3-1. 문단의 전형적 내부 구조
- 한 문단은 보통 몇 문장으로 구성되는가?
- 첫 문장과 이후 문장들의 관계는? (두괄식? 점층식?)
- 문장 길이의 리듬은? (짧-긴-짧? 균일?)

#### 3-2. 문장 수준의 특징
- 단문과 복문의 교차 패턴
- 접속사/접속 부사 사용 빈도
- 인용문 삽입 방식 (직접 인용? 간접 인용? 배치 위치?)

---

위 모든 항목에 대해, **실제 기사에서 직접 인용한 예시**를 반드시 포함하십시오.
추상적 서술보다 구체적 예시가 훨씬 중요합니다.
"""


# ---------------------------------------------------------------------------
# Phase 2: 목소리 프로필 추출 프롬프트
# ---------------------------------------------------------------------------

VOICE_SYSTEM_PROMPT = """당신은 문체 분석 전문가입니다.
주어진 기사들에서 저자의 '목소리(Voice)'를 포착하여,
다른 사람이 이 저자인 것처럼 글을 쓸 수 있게 하는 간결한 가이드를 작성합니다.

학술적 분석이 아니라, 실전적 가이드입니다.
"이 저자처럼 쓰려면 이렇게 하라"가 핵심입니다."""

VOICE_USER_PROMPT_TEMPLATE = """아래는 한 저자가 작성한 연작 기획기사 {n}편입니다.
이 저자의 '목소리'를 재현하기 위한 간결한 가이드를 작성하십시오.

---

## 분석 대상 기사

{articles_block}

---

## 요청 사항

아래 항목들을 **간결하고 실전적으로** 기술하십시오.
각 항목은 3~5문장 이내로 핵심만 전달하십시오.
가능한 한 실제 기사에서 인용하여 예시를 포함하십시오.

### 1. 페르소나 한 줄 정의
이 저자의 화자적 정체성을 한 문장으로 정의하십시오.
(예: "ESG 현장을 직접 취재하는 전문 기자로, 기업 활동의 사회적 의미를 독자 눈높이에서 풀어내는 목소리")

### 2. 톤과 온도
- 이 저자의 글은 어떤 온도인가? (냉정한/따뜻한/중립적/열정적)
- 기업 ESG 활동을 어떤 시선으로 바라보는가?
- 비판적 거리두기와 긍정적 옹호의 비율은?

### 3. 문장의 맛
- 이 저자 특유의 문장 리듬을 3문장으로 설명하십시오.
- 대표적인 "이 저자다운 문장"을 5개 인용하십시오.

### 4. 어휘 수준
- 전문 용어를 어느 정도 사용하는가?
- 한자어와 고유어의 비율은?
- 이 저자가 절대 쓰지 않을 것 같은 표현은?

### 5. 화자 가시성
- 1인칭(나/우리)을 사용하는가? 어디서, 얼마나?
- 독자를 직접 호명하는가?

### 6. 감성과 분석의 배합
- 사실 전달과 의미 부여의 비율은?
- 감성적 표현이 등장하는 위치는? (도입부? 마무리? 전체?)

### 7. 이 저자처럼 쓰기 위한 핵심 DO/DON'T (각 5개)

**DO (이렇게 써야 한다):**
1. ...
2. ...

**DON'T (이렇게 쓰면 안 된다):**
1. ...
2. ...

### 8. 번역투 및 LLM 패턴 회피
이 저자의 자연스러운 한국어를 재현하기 위해 반드시 피해야 할 표현 패턴을 나열하십시오.
(이중피동, "-에 의해", 물주구문, 불필요한 지시어, 접속 부사 과용, '-ㄹ 수 있다' 과용 등)
"""


class StyleDNA:
    """
    DATA 기사 저자의 문체를 재현 가능한 형태로 추출하고 관리한다.

    추출물:
      - blueprint: 구조적 청사진 + 표현 은행 (구체적·실전적)
      - voice: 목소리 프로필 (간결·실전적)
      - metrics: 정량 지표 (로컬 계산)
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model

        self.articles: list[dict] = []
        self.blueprint: str = ""        # 구조적 청사진 + 표현 은행
        self.voice: str = ""            # 목소리 프로필
        self.dna_document: str = ""     # 하위 호환용 (blueprint + voice 합본)
        self.raw_articles_text: str = ""

    # -------------------------------------------------------------------
    # 기사 로딩
    # -------------------------------------------------------------------

    def _api_call_with_retry(self, max_retries: int = 3, **kwargs) -> str:
        """API 호출을 rate limit 재시도 로직과 함께 수행한다."""
        import anthropic as _anthropic

        for attempt in range(max_retries):
            try:
                response = self.client.messages.create(**kwargs)
                return self._extract_text(response)
            except _anthropic.RateLimitError as e:
                if attempt == max_retries - 1:
                    raise
                wait = 60 * (attempt + 1) + 10  # 70초, 130초, 190초
                print(f"    Rate limit 도달. {wait}초 대기 후 재시도 ({attempt+1}/{max_retries})...")
                time.sleep(wait)
        return ""  # unreachable

    def load_articles_from_dir(self, dir_path: str, encoding: str = "utf-8") -> int:
        """디렉토리 내 .txt 파일을 로드한다."""
        p = Path(dir_path)
        count = 0
        for f in sorted(p.glob("*.txt")):
            text = f.read_text(encoding=encoding)
            if text.strip():
                self.articles.append({"title": f.stem, "text": text.strip()})
                count += 1
        return count

    def add_article(self, text: str, title: str = ""):
        """기사 한 편을 추가한다."""
        self.articles.append({"title": title, "text": text.strip()})

    # -------------------------------------------------------------------
    # 스타일 DNA 추출
    # -------------------------------------------------------------------

    def extract_dna(self, verbose: bool = True) -> str:
        """
        DATA 기사에서 재현 가이드를 추출한다.
        Phase 1: 구조적 청사진 + 표현 은행
        Phase 2: 목소리 프로필
        Phase 3: 정량 지표 (로컬 계산)
        """
        if not self.articles:
            raise ValueError("로드된 기사가 없습니다.")

        articles_block = self._build_articles_block()
        self.raw_articles_text = articles_block
        estimated_tokens = len(articles_block) / 1.8

        if verbose:
            print(f"  기사 {len(self.articles)}편, 약 {int(estimated_tokens):,}토큰")

        # Phase 1: 구조적 청사진 + 표현 은행
        if verbose:
            print(f"\n  [Phase 1/3] 구조적 청사진 + 표현 은행 추출 중...")

        if estimated_tokens > 120000:
            self.blueprint = self._extract_blueprint_batched(verbose)
        else:
            self.blueprint = self._extract_blueprint(articles_block)

        if verbose:
            print(f"    완료 ({len(self.blueprint):,}자)")

        # Rate limit 대기: Phase 1이 대량 토큰을 소비했으므로 충분히 대기
        wait_sec = max(int(estimated_tokens / 30000) * 60 + 10, 70)
        if verbose:
            print(f"\n  API rate limit 대기 중 ({wait_sec}초)...")
        time.sleep(wait_sec)

        # Phase 2: 목소리 프로필
        if verbose:
            print(f"\n  [Phase 2/3] 목소리 프로필 추출 중...")

        if estimated_tokens > 120000:
            self.voice = self._extract_voice_batched(verbose)
        else:
            self.voice = self._extract_voice(articles_block)

        if verbose:
            print(f"    완료 ({len(self.voice):,}자)")

        # Phase 3: 정량 지표
        if verbose:
            print(f"\n  [Phase 3/3] 정량 지표 계산 중...")

        metrics = self.compute_metrics()

        if verbose:
            print(f"    완료")

        # 합본 (하위 호환 + 단일 참조용)
        self.dna_document = (
            "# 구조적 청사진 + 표현 은행\n\n"
            + self.blueprint
            + "\n\n---\n\n"
            + "# 목소리 프로필\n\n"
            + self.voice
        )

        if verbose:
            print(f"\n  전체 추출 완료 ({len(self.dna_document):,}자)")

        return self.dna_document

    def _extract_blueprint(self, articles_block: str) -> str:
        """구조적 청사진 + 표현 은행을 추출한다."""
        user_prompt = BLUEPRINT_USER_PROMPT_TEMPLATE.format(
            n=len(self.articles),
            articles_block=articles_block,
        )
        return self._api_call_with_retry(
            model=self.model,
            max_tokens=12000,
            temperature=0.2,
            system=BLUEPRINT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

    def _extract_voice(self, articles_block: str) -> str:
        """목소리 프로필을 추출한다."""
        user_prompt = VOICE_USER_PROMPT_TEMPLATE.format(
            n=len(self.articles),
            articles_block=articles_block,
        )
        return self._api_call_with_retry(
            model=self.model,
            max_tokens=6000,
            temperature=0.2,
            system=VOICE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

    def _extract_blueprint_batched(self, verbose: bool) -> str:
        """기사가 많을 때 배치 분할 후 종합한다."""
        batch_size = 5
        batches = self._make_batches(batch_size)
        partial = []

        for i, batch_block in enumerate(batches):
            if verbose:
                print(f"    배치 {i+1}/{len(batches)} 분석 중...")
            user_prompt = BLUEPRINT_USER_PROMPT_TEMPLATE.format(
                n=len(self.articles),
                articles_block=batch_block,
            )
            result = self._api_call_with_retry(
                model=self.model,
                max_tokens=10000,
                temperature=0.2,
                system=BLUEPRINT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            partial.append(result)
            time.sleep(65)  # 배치 간 rate limit 대기

        if verbose:
            print("    배치 결과 종합 중...")

        synthesis = f"""아래는 한 저자의 연작 기사를 배치별로 분석한 결과입니다.
이 {len(batches)}개의 부분 분석을 하나의 통합된 구조적 청사진 + 표현 은행으로 종합하십시오.

배치 간 공통적으로 나타나는 패턴을 강화하고, 변동이 있는 부분은 조건부로 처리하십시오.

{chr(10).join(f"=== 배치 {i+1} ==={chr(10)}{a}" for i, a in enumerate(partial))}
"""
        return self._api_call_with_retry(
            model=self.model,
            max_tokens=12000,
            temperature=0.2,
            system=BLUEPRINT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": synthesis}],
        )

    def _extract_voice_batched(self, verbose: bool) -> str:
        """기사가 많을 때 배치 분할 후 종합한다."""
        batch_size = 5
        batches = self._make_batches(batch_size)
        partial = []

        for i, batch_block in enumerate(batches):
            if verbose:
                print(f"    배치 {i+1}/{len(batches)} 분석 중...")
            user_prompt = VOICE_USER_PROMPT_TEMPLATE.format(
                n=len(self.articles),
                articles_block=batch_block,
            )
            result = self._api_call_with_retry(
                model=self.model,
                max_tokens=4000,
                temperature=0.2,
                system=VOICE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            partial.append(result)
            time.sleep(65)  # 배치 간 rate limit 대기

        if verbose:
            print("    배치 결과 종합 중...")

        synthesis = f"""아래는 한 저자의 연작 기사를 배치별로 분석한 결과입니다.
이 {len(batches)}개의 부분 분석을 하나의 통합된 목소리 프로필로 종합하십시오.

{chr(10).join(f"=== 배치 {i+1} ==={chr(10)}{a}" for i, a in enumerate(partial))}
"""
        return self._api_call_with_retry(
            model=self.model,
            max_tokens=6000,
            temperature=0.2,
            system=VOICE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": synthesis}],
        )

    def _make_batches(self, batch_size: int) -> list[str]:
        """기사를 배치로 분할한다."""
        batches = []
        for i in range(0, len(self.articles), batch_size):
            batch = self.articles[i:i + batch_size]
            block = "\n\n---\n\n".join(
                f"### 기사 {i+j+1}: {a['title']}\n\n{a['text']}"
                for j, a in enumerate(batch)
            )
            batches.append(block)
        return batches

    # -------------------------------------------------------------------
    # 저장 / 로드
    # -------------------------------------------------------------------

    def save(self, path: str):
        """추출 결과를 JSON으로 저장한다."""
        data = {
            "blueprint": self.blueprint,
            "voice": self.voice,
            "dna_document": self.dna_document,
            "article_titles": [a["title"] for a in self.articles],
            "article_count": len(self.articles),
            "articles": self.articles,
            "metrics": self.compute_metrics(),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str) -> str:
        """저장된 결과를 로드한다."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.blueprint = data.get("blueprint", "")
        self.voice = data.get("voice", "")
        self.dna_document = data.get("dna_document", "")
        self.articles = data.get("articles", [])
        self._cached_metrics = data.get("metrics", None)

        # v3 이하 하위 호환: blueprint/voice가 없고 dna_document만 있는 경우
        if not self.blueprint and self.dna_document:
            self.blueprint = self.dna_document
            self.voice = ""

        return self.dna_document

    # -------------------------------------------------------------------
    # 정량 지표 계산
    # -------------------------------------------------------------------

    def compute_metrics(self) -> dict:
        """DATA 기사들의 정량 지표를 계산한다."""
        if hasattr(self, '_cached_metrics') and self._cached_metrics:
            return self._cached_metrics

        if not self.articles:
            return {}

        per_article = []
        all_para_lengths = []
        all_sentence_lengths = []
        all_first_sentence_lengths = []
        all_subheading_counts = []
        all_paras_per_subheading = []

        for art in self.articles:
            text = art["text"].strip()
            raw_lines = [ln.strip() for ln in text.split('\n') if ln.strip()]

            # 제목/부제 건너뛰기
            body_start = 0
            for i, ln in enumerate(raw_lines):
                if len(ln) >= 100 or i >= 5:
                    body_start = i
                    break
            body_lines = raw_lines[body_start:]

            # 중간제목 감지 + 본문 문단 분리
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
            para_sentences = []
            first_sentences = []
            for para in body_paragraphs:
                sentences = self._split_sentences(para)
                if sentences:
                    para_sentences.append(sentences)
                    first_sentences.append(sentences[0])
                    all_sentence_lengths.extend(len(s) for s in sentences)
                    all_first_sentence_lengths.append(len(sentences[0]))

            subheading_count = len(subheadings)
            all_subheading_counts.append(subheading_count)
            if subheading_count > 0:
                paras_per_sub = len(body_paragraphs) / (subheading_count + 1)
                all_paras_per_subheading.append(paras_per_sub)

            article_length = sum(len(p) for p in body_paragraphs)
            para_count = len(body_paragraphs)
            para_lengths = [len(p) for p in body_paragraphs]
            all_para_lengths.extend(para_lengths)

            per_article.append({
                "title": art["title"],
                "total_length": article_length,
                "paragraph_count": para_count,
                "paragraph_lengths": para_lengths,
                "avg_paragraph_length": round(sum(para_lengths) / max(len(para_lengths), 1), 1),
                "subheading_count": subheading_count,
                "subheadings": subheadings,
                "sentence_count": sum(len(ss) for ss in para_sentences),
                "avg_sentence_length": round(
                    sum(sum(len(s) for s in ss) for ss in para_sentences) /
                    max(sum(len(ss) for ss in para_sentences), 1), 1
                ),
                "avg_first_sentence_length": round(
                    sum(len(fs) for fs in first_sentences) / max(len(first_sentences), 1), 1
                ),
            })

        n_articles = len(per_article)

        avg_article_length = round(sum(a["total_length"] for a in per_article) / n_articles, 1)
        avg_paragraph_count = round(sum(a["paragraph_count"] for a in per_article) / n_articles, 1)
        avg_paragraph_length = round(sum(all_para_lengths) / max(len(all_para_lengths), 1), 1)
        avg_sentence_length = round(sum(all_sentence_lengths) / max(len(all_sentence_lengths), 1), 1)
        avg_first_sentence_length = round(sum(all_first_sentence_lengths) / max(len(all_first_sentence_lengths), 1), 1)
        avg_subheading_count = round(sum(all_subheading_counts) / n_articles, 1)
        avg_paras_per_subheading = round(
            sum(all_paras_per_subheading) / max(len(all_paras_per_subheading), 1), 1
        ) if all_paras_per_subheading else 0

        metrics = {
            "avg_article_length": avg_article_length,
            "avg_paragraph_count": avg_paragraph_count,
            "avg_paragraph_length": avg_paragraph_length,
            "avg_sentence_length": avg_sentence_length,
            "avg_first_sentence_length": avg_first_sentence_length,
            "avg_subheading_count": avg_subheading_count,
            "avg_paras_per_subheading": avg_paras_per_subheading,
            "tolerance": 0.05,
            "bounds": {
                "article_length_min": round(avg_article_length * 0.95, 1),
                "article_length_max": round(avg_article_length * 1.05, 1),
                "paragraph_count_min": round(avg_paragraph_count * 0.95, 1),
                "paragraph_count_max": round(avg_paragraph_count * 1.05, 1),
                "paragraph_length_min": round(avg_paragraph_length * 0.95, 1),
                "paragraph_length_max": round(avg_paragraph_length * 1.05, 1),
                "sentence_length_min": round(avg_sentence_length * 0.95, 1),
                "sentence_length_max": round(avg_sentence_length * 1.05, 1),
                "first_sentence_length_max": round(avg_first_sentence_length * 1.2, 1),
            },
            "per_article": per_article,
        }

        self._cached_metrics = metrics
        return metrics

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """한국어 텍스트를 문장 단위로 분리한다."""
        pattern = r'(?<=[다요음임함됨까나라지죠군요][\.\?!])\s+'
        parts = re.split(pattern, text.strip())
        result = []
        for part in parts:
            sub = re.split(r'(?<=다\.)\s+|(?<=요\.)\s+|(?<=임\.)\s+|(?<=함\.)\s+', part)
            result.extend(sub)
        return [s.strip() for s in result if s.strip() and len(s.strip()) >= 5]

    def get_metrics(self) -> dict:
        if hasattr(self, '_cached_metrics') and self._cached_metrics:
            return self._cached_metrics
        return self.compute_metrics()

    def format_metrics_summary(self) -> str:
        """정량 지표를 포맷한다."""
        m = self.get_metrics()
        if not m:
            return "정량 지표 없음"
        b = m["bounds"]
        lines = [
            f"DATA 기사 정량 지표 (±5% 허용 범위)",
            f"  기사 총 길이:      평균 {m['avg_article_length']:,.0f}자  (허용: {b['article_length_min']:,.0f}~{b['article_length_max']:,.0f}자)",
            f"  문단 수:           평균 {m['avg_paragraph_count']:.1f}개  (허용: {b['paragraph_count_min']:.1f}~{b['paragraph_count_max']:.1f}개)",
            f"  문단 길이:         평균 {m['avg_paragraph_length']:,.0f}자  (허용: {b['paragraph_length_min']:,.0f}~{b['paragraph_length_max']:,.0f}자)",
            f"  문장 평균 길이:    {m['avg_sentence_length']:.0f}자  (허용: {b['sentence_length_min']:.0f}~{b['sentence_length_max']:.0f}자)",
            f"  첫 문장 평균 길이: {m['avg_first_sentence_length']:.0f}자  (상한: {b['first_sentence_length_max']:.0f}자)",
            f"  중간제목:          평균 {m['avg_subheading_count']:.1f}개/기사",
        ]
        if m['avg_paras_per_subheading'] > 0:
            lines.append(f"  중간제목 간격:     {m['avg_paras_per_subheading']:.1f}문단마다")
        if m.get("per_article"):
            lines.append(f"\n  기사별 상세:")
            for a in m["per_article"]:
                sub_info = f", 중간제목 {a['subheading_count']}개" if a.get("subheadings") else ""
                lines.append(
                    f"    {a['title']}: {a['total_length']:,}자, {a['paragraph_count']}문단, "
                    f"문단평균 {a['avg_paragraph_length']:.0f}자, 문장평균 {a.get('avg_sentence_length', 0):.0f}자, "
                    f"첫문장평균 {a.get('avg_first_sentence_length', 0):.0f}자{sub_info}"
                )
                if a.get("subheadings"):
                    for sh in a["subheadings"][:5]:
                        lines.append(f"      └ \"{sh}\"")
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # 유틸리티
    # -------------------------------------------------------------------

    def _build_articles_block(self) -> str:
        parts = []
        for i, art in enumerate(self.articles, 1):
            parts.append(f"### 기사 {i}: {art['title']}\n\n{art['text']}")
        return "\n\n---\n\n".join(parts)

    def get_best_examples(self, n: int = 3) -> list[dict]:
        """few-shot 예시로 사용할 기사를 선별한다."""
        if len(self.articles) <= n:
            return self.articles.copy()
        indices = []
        step = max(1, (len(self.articles) - 1) / (n - 1))
        for i in range(n):
            idx = min(int(i * step), len(self.articles) - 1)
            if idx not in indices:
                indices.append(idx)
        while len(indices) < n and len(indices) < len(self.articles):
            for idx in range(len(self.articles)):
                if idx not in indices:
                    indices.append(idx)
                    break
        return [self.articles[i] for i in sorted(indices)]

    @staticmethod
    def _extract_text(response) -> str:
        return "".join(
            block.text for block in response.content if block.type == "text"
        )
