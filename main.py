"""
main.py (v4.0)
==============
ESG 기획기사 자동 작성 시스템 — 구체적 재현 아키텍처.

v4.0의 핵심 변화:
  - 추상적 12축 분석 → 구체적 재현 가이드
    · 구조적 청사진 (문단별 흐름 템플릿)
    · 표현 은행 (실제 문장·구문 수집)
    · 목소리 가이드 (간결한 실전 지침)
  - 검증 시 DATA 기사와 직접 비교

사용법:
  # 1단계: DATA 기사에서 재현 가이드 추출
  python main.py learn --articles-dir ./data/my_articles/

  # 2단계: 보도자료 → 기사 생성
  python main.py generate --press-release ./data/press_release.txt

  # 앵글 제안
  python main.py suggest --press-release ./data/press_release.txt

  # 대화형 모드
  python main.py interactive
"""

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import argparse
import os
import sys
from pathlib import Path

from style_dna import StyleDNA
from generator import ArticleGenerator


# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
DNA_PATH = "./data/style_dna.json"
DEFAULT_ARTICLES_DIR = "./data/my_articles/"
OUTPUT_DIR = "./output/"


# ---------------------------------------------------------------------------
# learn
# ---------------------------------------------------------------------------
def cmd_learn(args):
    """DATA 기사에서 재현 가이드를 추출한다."""
    articles_dir = args.articles_dir or DEFAULT_ARTICLES_DIR
    model = args.model or "sonnet"

    if not Path(articles_dir).exists():
        print(f"오류: '{articles_dir}' 디렉토리가 존재하지 않습니다.")
        sys.exit(1)

    txt_files = list(Path(articles_dir).glob("*.txt"))
    if not txt_files:
        print(f"오류: '{articles_dir}'에 .txt 파일이 없습니다.")
        sys.exit(1)

    print(f"{'='*60}")
    print(f"재현 가이드 추출 v4.0")
    print(f"{'='*60}")
    print(f"  대상: {articles_dir}")
    print(f"  파일: {len(txt_files)}개")
    print(f"  모델: {model}")
    print()

    dna = StyleDNA(model=ArticleGenerator.MODELS.get(model, model))
    count = dna.load_articles_from_dir(articles_dir)
    print(f"  {count}편 로드 완료")

    dna.extract_dna(verbose=True)

    os.makedirs(Path(DNA_PATH).parent, exist_ok=True)
    dna.save(DNA_PATH)
    print(f"\n  저장: {DNA_PATH}")

    print(f"\n  {dna.format_metrics_summary()}")

    print(f"\n{'='*60}")
    print("구조적 청사진 미리보기 (처음 1500자)")
    print(f"{'='*60}")
    print(dna.blueprint[:1500])
    if len(dna.blueprint) > 1500:
        print(f"\n... (총 {len(dna.blueprint):,}자)")

    print(f"\n{'='*60}")
    print("목소리 프로필 미리보기 (처음 1000자)")
    print(f"{'='*60}")
    print(dna.voice[:1000])
    if len(dna.voice) > 1000:
        print(f"\n... (총 {len(dna.voice):,}자)")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------
def cmd_generate(args):
    """보도자료를 ESG 기획기사로 변환한다."""
    source_path = args.press_release
    model = args.model or "sonnet"
    temperature = args.temperature or 0.7
    angle = args.angle or ""
    n_examples = args.examples or 3

    # 1. DNA 로드
    if not Path(DNA_PATH).exists():
        print(f"오류: 재현 가이드가 없습니다 ({DNA_PATH})")
        print(f"먼저 `python main.py learn --articles-dir ...` 를 실행하십시오.")
        sys.exit(1)

    dna = StyleDNA()
    dna.load(DNA_PATH)
    metrics = dna.get_metrics()

    print(f"재현 가이드 로드 완료 (기사 {len(dna.articles)}편 기반)")
    if metrics:
        print(f"\n{dna.format_metrics_summary()}")

    # 2. 보도자료 읽기
    source_text = Path(source_path).read_text(encoding="utf-8")
    print(f"보도자료 로드: {source_path} ({len(source_text):,}자)")

    # 3. 예시 기사 선택
    examples = dna.get_best_examples(n=n_examples)
    print(f"DATA 기사 {len(examples)}편 선택")

    # 4. 프롬프트 빌드
    gen = ArticleGenerator(model=model, max_tokens=8192)
    system_prompt = gen.build_system_prompt(
        dna.blueprint, dna.voice, examples, metrics
    )

    total_chars = len(system_prompt) + len(source_text)
    est_tokens = int(total_chars / 1.8)
    print(f"프롬프트 크기: 약 {total_chars:,}자 (추정 {est_tokens:,}토큰)")

    if est_tokens > 180000:
        print(f"\n경고: 프롬프트가 큽니다. 예시 기사 수를 줄입니다.")
        examples = dna.get_best_examples(n=2)
        system_prompt = gen.build_system_prompt(
            dna.blueprint, dna.voice, examples, metrics
        )

    # 5. 생성
    print(f"\n{'='*60}")
    print(f"ESG 기획기사 생성 시작")
    print(f"{'='*60}")

    result = gen.generate(
        system_prompt=system_prompt,
        press_release=source_text,
        angle=angle,
        temperature=temperature,
        blueprint=dna.blueprint,
        voice=dna.voice,
        metrics=metrics,
        example_articles=examples,
        verbose=True,
    )

    # 6. 출력
    final = result["final"]
    print(f"\n{'='*60}")
    print(f"최종 기사")
    print(f"{'='*60}")
    print(final)
    print(f"{'='*60}")

    for label, key in [
        ("DATA 대조 검증 보고서", "style_check"),
        ("보도자료 반영도 검증 보고서", "coverage_check"),
        ("정량 지표 검증 — 초안", "metrics_check"),
        ("정량 지표 검증 — 최종본", "metrics_check_final"),
    ]:
        if result.get(key):
            print(f"\n{'='*60}")
            print(f"[{label}]")
            print(f"{'='*60}")
            print(result[key])

    # 7. 저장
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    out_path = Path(OUTPUT_DIR) / "article.txt"
    out_path.write_text(final, encoding="utf-8")
    print(f"\n저장: {out_path}")

    if result["draft"] != result["final"]:
        draft_path = Path(OUTPUT_DIR) / "article_draft.txt"
        draft_path.write_text(result["draft"], encoding="utf-8")
        print(f"초안 저장: {draft_path}")

    if result.get("outline"):
        outline_path = Path(OUTPUT_DIR) / "outline.txt"
        outline_path.write_text(result["outline"], encoding="utf-8")
        print(f"기획안 저장: {outline_path}")

    report_parts = []
    if result.get("outline"):
        report_parts.append(f"=== 기획안 (Theme & Outline) ===\n\n{result['outline']}")
    for label, key in [
        ("DATA 대조 검증", "style_check"),
        ("반영도 검증", "coverage_check"),
        ("정량 지표 검증 (초안)", "metrics_check"),
        ("정량 지표 검증 (최종본)", "metrics_check_final"),
        ("최종 교정 사항", "refinement_notes"),
    ]:
        if result.get(key):
            report_parts.append(f"=== {label} ===\n\n{result[key]}")

    if report_parts:
        report_path = Path(OUTPUT_DIR) / "verification_report.txt"
        report_path.write_text("\n\n".join(report_parts), encoding="utf-8")
        print(f"검증 보고서 저장: {report_path}")


# ---------------------------------------------------------------------------
# suggest
# ---------------------------------------------------------------------------
def cmd_suggest(args):
    """보도자료에 대한 기획기사 앵글을 제안한다."""
    source_path = args.press_release
    model = args.model or "sonnet"

    if not Path(DNA_PATH).exists():
        print("오류: 재현 가이드가 없습니다. 먼저 learn을 실행하십시오.")
        sys.exit(1)

    dna = StyleDNA()
    dna.load(DNA_PATH)

    source_text = Path(source_path).read_text(encoding="utf-8")

    gen = ArticleGenerator(model=model)
    print("앵글 제안 생성 중...\n")
    suggestions = gen.suggest_angles(
        source_text, dna.blueprint, dna.voice, n_angles=3
    )

    print(f"{'='*60}")
    print("기획기사 앵글 제안")
    print(f"{'='*60}")
    print(suggestions)
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# interactive
# ---------------------------------------------------------------------------
def cmd_interactive(args):
    """대화형 모드."""
    model = args.model or "sonnet"

    if not Path(DNA_PATH).exists():
        print(f"오류: 재현 가이드가 없습니다 ({DNA_PATH})")
        sys.exit(1)

    dna = StyleDNA()
    dna.load(DNA_PATH)
    metrics = dna.get_metrics()

    gen = ArticleGenerator(model=model)
    examples = dna.get_best_examples(n=3)
    sys_prompt = gen.build_system_prompt(
        dna.blueprint, dna.voice, examples, metrics
    )

    print(f"재현 가이드 로드 완료 (기사 {len(dna.articles)}편)")
    print(f"\n{'='*60}")
    print("대화형 ESG 기획기사 생성 모드")
    print(f"{'='*60}")

    last_article = None
    last_source = None

    while True:
        print(f"\n{'-'*40}")
        options = ["[1] 보도자료 → 기획기사 생성"]
        if last_article:
            options.append("[2] 이전 기사 수정")
        options.append("[3] 앵글 제안")
        options.append("[q] 종료")
        print("\n".join(options))

        choice = input("선택: ").strip()

        if choice in ("q", "quit", "exit"):
            print("종료합니다.")
            break

        elif choice == "1":
            print("\n보도자료를 붙여넣으십시오 (완료: 빈 줄에 END 입력):")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip().upper() == "END":
                    break
                lines.append(line)

            source_text = "\n".join(lines).strip()
            if not source_text:
                print("입력이 비어 있습니다.")
                continue

            last_source = source_text
            angle = input("기사 방향/앵글 (없으면 Enter): ").strip()

            print("\n기사 생성 중...\n")
            result = gen.generate(
                system_prompt=sys_prompt,
                press_release=source_text,
                angle=angle,
                temperature=0.7,
                blueprint=dna.blueprint,
                voice=dna.voice,
                metrics=metrics,
                example_articles=examples,
                verbose=True,
            )

            print(f"\n{'='*60}")
            print("최종 기사")
            print(f"{'='*60}")
            print(result["final"])
            print(f"{'='*60}")

            last_article = result["final"]
            _save_interactive(result)

        elif choice == "2" and last_article:
            feedback = input("수정 요청: ").strip()
            if not feedback:
                continue
            print("\n재생성 중...\n")
            revised = gen.regenerate_with_feedback(
                sys_prompt, last_source, last_article, feedback,
            )
            print(revised)
            last_article = revised
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            Path(OUTPUT_DIR, "article_latest.txt").write_text(revised, encoding="utf-8")

        elif choice == "3":
            if not last_source:
                print("\n보도자료를 먼저 입력하십시오 (완료: 빈 줄에 END 입력):")
                lines = []
                while True:
                    try:
                        line = input()
                    except EOFError:
                        break
                    if line.strip().upper() == "END":
                        break
                    lines.append(line)
                last_source = "\n".join(lines).strip()
                if not last_source:
                    continue
            print("\n앵글 제안 생성 중...\n")
            suggestions = gen.suggest_angles(
                last_source, dna.blueprint, dna.voice
            )
            print(suggestions)


def _save_interactive(result: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    Path(OUTPUT_DIR, "article_latest.txt").write_text(result["final"], encoding="utf-8")
    print(f"\n저장: {OUTPUT_DIR}article_latest.txt")

    report_parts = []
    for label, key in [("DATA 대조 검증", "style_check"), ("반영도 검증", "coverage_check")]:
        if result.get(key):
            report_parts.append(f"=== {label} ===\n\n{result[key]}")
    if report_parts:
        Path(OUTPUT_DIR, "verification_report.txt").write_text(
            "\n\n".join(report_parts), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="ESG 기획기사 자동 작성 시스템 v4.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 순서:
  1. python main.py learn --articles-dir ./data/my_articles/
  2. python main.py generate --press-release ./data/press_release.txt

기타:
  python main.py suggest --press-release ./data/press_release.txt
  python main.py interactive
""",
    )

    sub = parser.add_subparsers(dest="command")

    p_learn = sub.add_parser("learn", help="DATA 기사에서 재현 가이드 추출")
    p_learn.add_argument("--articles-dir", default=None)
    p_learn.add_argument("--model", default="sonnet")

    p_gen = sub.add_parser("generate", help="보도자료 → 기사")
    p_gen.add_argument("--press-release", required=True, help="보도자료 .txt 파일 경로")
    p_gen.add_argument("--model", default="sonnet")
    p_gen.add_argument("--temperature", type=float, default=None)
    p_gen.add_argument("--angle", default="")
    p_gen.add_argument("--examples", type=int, default=3)

    p_sug = sub.add_parser("suggest", help="앵글 제안")
    p_sug.add_argument("--press-release", required=True)
    p_sug.add_argument("--model", default="sonnet")

    p_int = sub.add_parser("interactive", help="대화형 모드")
    p_int.add_argument("--model", default="sonnet")

    args = parser.parse_args()

    if args.command == "learn":
        cmd_learn(args)
    elif args.command == "generate":
        cmd_generate(args)
    elif args.command == "suggest":
        cmd_suggest(args)
    elif args.command == "interactive":
        cmd_interactive(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
