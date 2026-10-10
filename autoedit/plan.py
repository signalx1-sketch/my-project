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
        "fix": {
            "type": "array",
            "description": "음성 인식이 틀리게 적은 표기 → 올바른 표기 (약 이름, 의학 용어)",
            "items": {
                "type": "object",
                "properties": {"wrong": {"type": "string"}, "right": {"type": "string"}},
                "required": ["wrong", "right"],
                "additionalProperties": False,
            },
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
    "required": ["title", "hooks", "chapters", "keywords", "fix", "skip"],
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
- 대본은 음성 인식 결과라서 약 이름, 의학 용어가 틀리게 적힌 경우가 많다.
  fix에 {"wrong": 틀린 표기, "right": 올바른 표기}로 적는다. 예: 디페린결 → 디페린겔.
  keywords에는 고친 뒤의 표기를 쓴다.
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
        "fix": {},
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
    plan.setdefault("fix", {})
    if isinstance(plan["fix"], list):  # API 응답은 [{"wrong", "right"}] 목록
        plan["fix"] = {f["wrong"]: f["right"] for f in plan["fix"] if f["wrong"]}
    plan.setdefault("title", "")
    out_json.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  편집 계획: {source} (콜드 오픈 {len(plan['hooks'])}구간, 챕터 {len(plan['chapters'])}개)")
    return plan


BROLL_SCHEMA = {
    "type": "object",
    "properties": {
        "broll": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "at": {"type": "integer", "description": "자료가 나올 문장 번호"},
                    "offset": {"type": "number", "description": "그 문장 시작 후 몇 초 뒤에 띄울지 (보통 0, 긴 문장 중간이면 6~12)"},
                    "asset": {"type": "string", "description": "자료 목록의 파일 경로 그대로"},
                    "mode": {"type": "string", "enum": ["full", "side"]},
                },
                "required": ["at", "offset", "asset", "mode"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["broll"],
    "additionalProperties": False,
}

BROLL_PROMPT = """너는 피부 질환 전문 의료 유튜브 채널의 편집 감독이다.
대본(번호 붙은 문장)과 자료 화면 목록을 보고, 어느 문장에 어떤 자료를 띄울지 고른다.

- full: 화면 전체를 3초 덮는다. 말하는 내용을 장면으로 보여줄 때 (연고 바르는 손, 붉어진 얼굴,
  병원 진료, 주사 맞는 장면 등). 화면이 자주 바뀌어야 지루하지 않으므로 8~12초에 한 번꼴로,
  영상 전체의 30% 안팎이 되게 넣는다. 긴 문장은 offset으로 중간에도 넣는다.
- side: 얼굴 옆에 작게 3.5초. 약 제품 사진, 논문 화면, 도표, 치료 전후 사진처럼 "이것"을 가리킬 때.
- full은 문장과 정확히 맞지 않아도 영상 주제(증상, 피부 관리, 병원)에 어울리면 된다. side는 정확히 맞을 때만.
- 같은 자료는 한 번만 쓰고, 비슷한 자료(같은 장소·같은 모델의 연속 사진)를 연달아 쓰지 않는다.
  영상과 사진, 클로즈업과 전신, 병원과 집 장면을 섞어서 다채롭게 한다.
- 인사말, 구독 안내 문장에는 넣지 않는다.
"""


def plan_broll(sentences: list[Sentence], assets: list, out_json: Path, use_ai: bool = True) -> list[dict]:
    """자료 화면 배치 계획. 결과는 out_json에 저장되고, 있으면 다시 쓴다."""
    from . import broll

    if out_json.exists():
        items = json.loads(out_json.read_text(encoding="utf-8"))
        print(f"  자료 화면 계획: 이전 실행 결과 ({len(items)}개 후보)")
        return items
    items = None
    if use_ai and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        import anthropic

        client = anthropic.Anthropic()
        content = (sentences_prompt(sentences) + "\n\n자료 화면 목록:\n" + broll.catalog_prompt(assets))
        try:
            with client.messages.stream(
                model=CLAUDE_MODEL, max_tokens=16000, system=BROLL_PROMPT,
                messages=[{"role": "user", "content": content}],
                output_config={"effort": "high", "format": {"type": "json_schema", "schema": BROLL_SCHEMA}},
            ) as stream:
                resp = stream.get_final_message()
            if resp.stop_reason != "refusal":
                text = next((b.text for b in resp.content if b.type == "text"), None)
                items = json.loads(text)["broll"] if text else None
        except anthropic.APIError as e:
            print(f"  Claude API 호출 실패, 파일명 규칙으로 진행합니다: {e}")
    source = "Claude API"
    if items is None:
        items = broll.suggest_with_rules(sentences, assets)
        source = "파일명/태그 규칙"
    out_json.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  자료 화면 계획: {source} ({len(items)}개 후보)")
    return items
