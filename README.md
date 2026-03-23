# ESG 기획기사 자동 작성 시스템 v4.1

보도자료를 입력하면, 특정 기자의 문체를 재현한 ESG 기획기사를 자동으로 생성하는 시스템입니다.

## 작동 원리

1. **학습(learn)**: 기자가 쓴 기사 모음(DATA 기사)을 분석하여 구조적 청사진, 표현 은행, 목소리 프로필을 추출합니다.
2. **생성(generate)**: 보도자료를 받아 6단계 파이프라인으로 기사를 생성합니다.
   - [1단계] 기획안 생성 — 핵심 테마(Narrative Anchor) + 문단별 논리 전개도
   - [2단계] 초안 집필 — 기획안을 골격으로 DATA 문체로 작성
   - [3단계] DATA 대조 검증 — DATA 기사와 직접 비교
   - [4단계] 보도자료 반영도 검증 — 누락·변형 점검
   - [5단계] 정량 지표 검증 — 문장 길이, 문단 수 등 DATA 수치와 비교
   - [6단계] 최종 교정 — 검증 결과를 반영하여 교정

## 설치

### 1. 저장소 클론

```bash
git clone https://github.com/YOUR_USERNAME/article-generator.git
cd article-generator
```

### 2. 의존성 설치

Python 3.10 이상이 필요합니다.

```bash
pip install -r requirements.txt
```

### 3. API 키 설정

[Anthropic Console](https://console.anthropic.com/)에서 API 키를 발급받으세요.

`.env.example`을 복사하여 `.env` 파일을 만들고, 키를 입력합니다:

```bash
cp .env.example .env
```

`.env` 파일을 열어서 키를 입력:
```
ANTHROPIC_API_KEY=sk-ant-여기에-당신의-키를-입력하세요
```

### 4. DATA 기사 준비

`data/my_articles/` 폴더를 만들고, 재현할 기자의 기사를 `.txt` 파일로 넣습니다.

```
data/my_articles/기사1.txt
data/my_articles/기사2.txt
...
```

기사 수가 많을수록 문체 재현이 정확합니다 (20~30편 권장).

## 사용법

### 스타일 학습 (최초 1회)

```bash
python main.py learn --articles-dir ./data/my_articles/
```

### 기사 생성

```bash
python main.py generate --press-release ./data/press_release.txt
```

### 앵글 제안

```bash
python main.py suggest --press-release ./data/press_release.txt
```

### 대화형 모드

```bash
python main.py interactive
```

### 옵션

```bash
# 앵글 지정
python main.py generate --press-release ./data/press_release.txt --angle "기술의 사회적 영향에 초점"

# 모델 변경 (sonnet/haiku/opus)
python main.py generate --press-release ./data/press_release.txt --model opus

# few-shot 예시 수 조절
python main.py generate --press-release ./data/press_release.txt --examples 5

# temperature 조절 (기본: 0.7)
python main.py generate --press-release ./data/press_release.txt --temperature 0.5
```

## 출력 파일

| 파일 | 내용 |
|------|------|
| `output/article.txt` | 최종 완성 기사 |
| `output/article_draft.txt` | 교정 전 초안 |
| `output/outline.txt` | 기획안 (핵심 테마 + 논리 전개도) |
| `output/verification_report.txt` | 검증 보고서 |

## 비용 안내 (Claude Sonnet 기준)

| 작업 | 예상 비용 |
|------|----------|
| 스타일 학습 (learn) | $0.10~0.30 (1회) |
| 기사 생성 (generate) | $0.10~0.25 |
| 앵글 제안 (suggest) | $0.01~0.03 |

## 파일 구조

```
article-generator/
├── main.py              # CLI 인터페이스
├── generator.py         # 6단계 생성 파이프라인
├── style_dna.py         # 스타일 분석·추출
├── requirements.txt     # 의존성 목록
├── .env                 # API 키 (git에 포함되지 않음)
├── .env.example         # API 키 템플릿
├── .gitignore           # git 제외 목록
├── data/
│   ├── my_articles/     # DATA 기사 (git에 포함되지 않음)
│   └── style_dna.json   # 학습 결과 (자동 생성)
└── output/              # 생성 결과 (자동 생성)
```

## 요구사항

- Python 3.10+
- Anthropic API 키 (Claude Sonnet/Opus/Haiku)
