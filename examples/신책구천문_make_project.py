import json, sys
from pptx import Presentation
from pptx.util import Pt, Inches
D = "deliverables/신책구천문"
# (문장 번호, 몇 초 뒤, 카드 설정)
C = [
 (0, 4.0, {"kind": "icontext", "big": "113만", "text": ["수나라 **113만** 대군", "을지문덕이 적장 우중문에게", "시 한 수를 보냅니다"]}),
 (1, 1.0, {"kind": "icontext", "icon": "scroll-text", "text": ["神策究天文 妙算窮地理", "戰勝功旣高 知足願云止"]}),
 (2, 0.5, {"kind": "iconlist", "rows": [["sparkles", "신묘한 계책은 천문을 다했고"], ["target", "묘한 셈은 지리를 꿰뚫었네"], ["award", "싸움에 이겨 공이 이미 높으니"], ["hand", "**족한 줄 알고 그만두게**"]], "foot": "을지문덕, 여수장우중문시"}),
 (2, 7.5, {"kind": "punch", "lines": [["족한 줄 알고"], ["그만두는 게", "어떠한가"]], "box": "어떠한가"}),
 (3, 0.5, {"kind": "image", "title": "리트 만점자 의혹", "src": f"{D}/기사4_조선일보_네이트.png"}),
 (5, 0.0, {"kind": "timeline", "title": "보도된 시험 이력", "nodes": [["재작년", "고려대 입학"], ["작년 수능", "1문제 틀리고 서울대 치대"], ["올해", "LEET 만점"]], "accent": 2}),
 (6, 3.0, {"kind": "image", "title": "과외교사 주장", "src": f"{D}/기사1_머니투데이.png"}),
 (8, 1.5, {"kind": "punch", "lines": [["리트는"], ["다 맞으라고 내는", "시험이 아닙니다"]], "box": "아닙니다"}),
 (12, 1.0, {"kind": "icontext", "big": "3번", "text": ["저도 **수능을 3번** 봤습니다"]}),
 (16, 2.0, {"kind": "compare2", "title": "시험의 진실", "left": {"title": "공부 못하는 학생", "sub": "시험을 잘 보기 어렵다", "bar": 0.2, "color": "#8A8A8A"}, "right": {"title": "공부 잘하는 학생", "sub": "시험을 못 보는 일은 흔하다", "bar": 0.75, "color": "#52B788"}}),
 (18, 0.0, {"kind": "punch", "lines": [["시험은"], ["운칠기삼"]], "box": "운칠기삼"}),
 (22, 0.0, {"kind": "bubble", "tone": "bad", "text": ["1학기 다니고", "한두 달 공부해서 리트 만점?"], "note": "말이 안 되는 거죠"}),
 (25, 0.5, {"kind": "icontext", "icon": "graduation-cap", "text": ["좋은 대학 나와서", "**몇 년씩** 준비하는 시험"]}),
 (28, 2.0, {"kind": "icontext", "icon": "calendar", "text": ["제 아들도 고3", "**내일 수능**을 봅니다"]}),
 (29, 0.5, {"kind": "punch", "lines": [["인생의 성공을", "결정짓는 건"], ["내면의 힘"]], "box": "내면의 힘"}),
 (33, 1.0, {"kind": "segments", "title": "인생도 운칠기삼", "segs": [{"label": "운 7", "w": 0.7, "color": "#5A5A5A"}, {"label": "기 3 · 내면의 힘", "w": 0.3, "color": "#52B788"}]}),
 (34, 3.0, {"kind": "icontext", "icon": "trending-up", "text": ["기삼이 있다면", "**학벌과 상관없이**", "성공한 인생을 삽니다"]}),
 (36, 0.0, {"kind": "punch", "lines": [["인생은"], ["그렇게", "만만하지 않습니다"]], "box": "만만하지"}),
 (39, 2.0, {"kind": "comment", "title": "유튜브 댓글", "name": "시청자", "text": "작년 서울대 예비 1번 아니냐"}),
 (40, 3.0, {"kind": "icontext", "icon": "users", "text": ["진짜 억울한 사람은", "밀리고 밀려 **막차를 놓친** 한 명"]}),
 (43, 0.0, {"kind": "punch", "lines": [["인생은"], ["깁니다"]], "box": "깁니다"}),
 (47, 0.0, {"kind": "icontext", "icon": "shield-check", "text": ["노력은", "**배신하지 않습니다**"]}),
 (49, 1.5, {"kind": "punch", "lines": [["가짜는"], ["다 드러나게", "돼 있습니다"]], "box": "드러나게"}),
 (51, 0.0, {"kind": "image", "title": "경찰 고발", "src": f"{D}/기사2_한국일보.png"}),
 (52, 3.5, {"kind": "image", "title": "경찰 수사 착수", "src": f"{D}/기사3_한국경제.png"}),
 (20, 5.0, {"kind": "icontext", "icon": "sparkles", "text": ["원하는 고득점이 나오려면", "**운**이 따라야 합니다"]}),
 (30, 1.0, {"kind": "icontext", "icon": "graduation-cap", "text": ["학벌도 **내면의 힘**으로", "얻어낸 것이라면 도움이 됩니다"]}),
 (31, 2.0, {"kind": "icontext", "icon": "trending-up", "text": ["좋은 학벌을 얻지 못했어도", "결국 **내면의 힘**으로 성공합니다"]}),
 (35, 1.0, {"kind": "icontext", "icon": "hourglass", "strike": True, "text": ["얕은 방법으로 들어간 좋은 학교", "그걸로 **인생이 성공**하진 않습니다"]}),
 (46, 0.5, {"kind": "compare2", "title": "살아 보니", "left": {"title": "불공평해 보여도", "sub": "당장은", "bar": 0.35, "color": "#8A8A8A"}, "right": {"title": "결국 공정하다", "sub": "길게 보면", "bar": 0.85, "color": "#52B788"}}),
]
prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
cards, slide_at = {}, {}
for no, (si, off, spec) in enumerate(C, 1):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    tb = s.shapes.add_textbox(Inches(1), Inches(3), Inches(11), Inches(1.5)).text_frame
    t = " ".join(spec.get("text", []) if isinstance(spec.get("text"), list) else [spec.get("title", "") or spec.get("kind")])
    tb.text = (t or spec["kind"]).replace("**", "")
    tb.paragraphs[0].runs[0].font.size = Pt(40)
    cards[str(no)] = spec
    slide_at[str(no)] = [si, off] if off else si
prs.save(sys.argv[1])
json.dump(cards, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
plan = {
 "title": "리트 만점자와 을지문덕의 시", "hooks": [], "keywords": [], "skip": [], "speed": [], "cut": [],
 "chapters": [{"from": 0, "label": "시험은 운칠기삼"}],
 "hook_text": "리트 만점자가\n**이 시**를 알았다면?",
 "fix": {"무증문": "우중문", "신책 9천문": "신책구천문", "묘산 궁지리": "묘산궁지리", "전승공기구": "전승공기고", "지족원운지": "지족원운지",
         "운치기삼": "운칠기삼", "0 .1 %": "0.1%", "세문량이 리트량이": "세무냥이 리트냥이", "빗보는": "빛 보는", "아기는": "악인은",
         "야튼 수작": "얕은 수작", "잔꽤": "잔꾀", "얕은 꽤": "얕은 꾀", "생년은": "설령", "113만 대군": "113만 대군"},
 "slide_at": slide_at, "slide_skip": [], "slide_hide": []}
json.dump(plan, open(sys.argv[3], "w"), ensure_ascii=False, indent=1)
print(len(C), "cards")
