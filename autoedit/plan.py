"""편집 계획: 콜드 오픈 문장, 챕터 라벨, 강조 키워드를 정한다.

세 가지 방법 중 하나로 만든다.
1. --plan 으로 받은 JSON 파일 (사람이나 Claude가 직접 작성)
2. ANTHROPIC_API_KEY 가 있으면 Claude API가 대본을 읽고 결정
3. 둘 다 없으면 키워드 규칙으로 콜드 오픈만 고른다
"""
import json
import os
from pathlib import Path

from .cuts import Sentence

CLAUDE_MODEL = "claude-opus-5-5"

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "인트로 범퍼에 띄울 짧은 제목 (15자 이내)"},
        "hooks": {
            "type": "array",
            "description": "영상 맨 앞 콜드 오픈에 쓸 문장 구간. 합쳐서 15~30초.",
            "items": {
                "type": "object",
                "properties": {"from": {"type": "integer"}, "to": {"type": "integer"}},
                "required": ["from", "to"],
                "additionalProperties": False,
            },
        },
        "chapters": {
            "type": "array",
            "description": "주제가 바뀌는 첫 문장 번호와 좌상단에 띄울 라벨 (20자 이내)",
            "items": {
                "type": "object",
                "properties": {"from": {"type": "integer"}, "label": {"type": "string"}},
                "required": ["from", "label"],
                "additionalProperties": False,
            },
        },
        "keywords": {
            "type": "array",
            "description": "자막에서 노란색으로 강조할 핵심 단어 (10~25개)",
            "items": {"type": "string"},
        },
        "skip": {
            "type": "array",
            "description": "본편에서 뺄 문장 구간 (NG, 같은 말 반복, 재촬영 앞부분)",
            "items": {
                "type": "object",
                "properties": {"from": {"type": "integer"}, "to": {"type": "integer"}},
                "required": ["from", "to"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "hooks", "chapters", "keywords", "skip"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """너는 피부 질환 전문 의료 유튜브 채널의 편집 감독이다.
의사 1인 토크 영상의 대본(번호가 붙은 문장 목록)을 읽고 편집 계획을 JSON으로 낸다.

이 채널에서 조회수가 높은 영상들의 공통점:
- 0초에 본편 중 가장 강한 발언을 15~30초 먼저 보여주는 콜드 오픈. 상식을 뒤집는 주장,
  "~하면 안 됩니다" 같은 경고, 시청자가 겪는 문제를 콕 집는 질문이 좋다.
  인사말, 자기소개, 병원 홍보, 환불 안내 문장은 콜드 오픈에 넣지 않는다.
  hooks 구간은 1~3개, 각 구간은 문맥 없이 들어도 이해되는 완결된 말이어야 한다.
- 좌상단에 지금 다루는 주제가 "Q. ~" 형태로 떠 있다. 챕터는 1~3분 간격으로 4~8개.
  label은 "Q."를 빼고 20자 이내로 쓴다. 첫 챕터는 0번 문장부터 시작한다.
- 핵심 단어(약 이름, 질환명, 부작용, 숫자, 결론 단어)만 노란색으로 강조한다.
  keywords는 대본에 실제로 나오는 표기 그대로 쓴다.
- skip에는 같은 말을 다시 시작한 NG 문장, 말이 꼬여서 바로 다시 말한 앞 문장만 넣는다.
  확실하지 않으면 비워 둔다.
"""


def sentences_prompt(sentences: list[Sentence]) -> str:
    lines = [f"[{s.idx}] ({s.start:.1f}s) {s.text}" for s in sentences]
    return "다음은 영상 대본이다. 편집 계획을 만들어라.\n\n" + "\n".join(lines)


def plan_with_claude(sentences: list[Sentence]) -> dict | None:
    """Claude API로 편집 계획을 만든다. 실패하면 None."""
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic()
    try:
        with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": sentences_prompt(sentences)}],
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
        ) as stream:
            response = stream.get_final_message()
    except anthropic.APIError as e:
        print(f"  Claude API 호출 실패, 규칙 기반으로 진행합니다: {e}")
        return None
    if response.stop_reason == "refusal":
        print("  Claude가 요청을 거절해서 규칙 기반으로 진행합니다.")
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    return json.loads(text) if text else None


HOOK_WORDS = ["절대", "반드시", "안 됩니다", "안됩니다", "마세요", "부작용", "문제는", "사실",
              "진짜", "왜", "악순환", "위험", "핵심", "대부분", "모르", "착각", "오히려"]


def plan_with_rules(sentences: list[Sentence]) -> dict:
    """API 없이 키워드 점수로 콜드 오픈 문장 2개만 고른다."""
    total = sentences[-1].end if sentences else 0
    scored = []
    for s in sentences:
        dur = s.end - s.start
        if s.start < total * 0.1 or not 3 <= dur <= 14:
            continue
        score = sum(s.text.count(k) for k in HOOK_WORDS) + (1 if "?" in s.text else 0)
        if score:
            scored.append((score, s.idx))
    scored.sort(key=lambda x: (-x[0], x[1]))
    hooks: list[int] = []
    for _, idx in scored:
        if all(abs(idx - h) > 3 for h in hooks):
            hooks.append(idx)
        if len(hooks) == 2:
            break
    return {
        "title": "",
        "hooks": [{"from": h, "to": h} for h in sorted(hooks)],
        "chapters": [],
        "keywords": [],
        "skip": [],
    }


def make_plan(sentences: list[Sentence], plan_file: Path | None, out_json: Path, use_ai: bool = True) -> dict:
    if plan_file:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        source = f"파일 {plan_file.name}"
    elif out_json.exists():
        plan = json.loads(out_json.read_text(encoding="utf-8"))
        source = "이전 실행 결과"
    else:
        plan = None
        if use_ai and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            print("  Claude API로 편집 계획을 만드는 중...")
            plan = plan_with_claude(sentences)
            source = "Claude API"
        if plan is None:
            plan = plan_with_rules(sentences)
            source = "키워드 규칙"
    for key in ("hooks", "chapters", "keywords", "skip"):
        plan.setdefault(key, [])
    plan.setdefault("title", "")
    out_json.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  편집 계획: {source} (콜드 오픈 {len(plan['hooks'])}구간, 챕터 {len(plan['chapters'])}개)")
    return plan
