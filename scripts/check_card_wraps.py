"""카드 글자 줄바꿈 검사 (2026-11-14): 렌더 전에 브라우저로 카드를 펼쳐 놓고
- 한두 글자만 다음 줄로 넘어간 곳 (예: '다른 병원 치 / 료')
- 낱말 가운데서 끊긴 곳 (예: '왔다갔 / 다')
을 찾는다. 줄바꿈은 애니메이션(투명도·이동)과 상관없으니 첫 화면 배치만 보면 된다.

사용법: python scripts/check_card_wraps.py 슬라이드.pptx 카드.json [계획.json]
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autoedit import motion_hf  # noqa: E402

JS = r"""
() => {
  const out = [];
  const isBlock = el => { const d = getComputedStyle(el).display; return !d.startsWith('inline') || d === 'inline-block' || d === 'inline-flex'; };
  for (const sec of document.querySelectorAll('section.clip')) {
    const groups = new Map();
    const walker = document.createTreeWalker(sec, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      if (!n.textContent.trim()) continue;
      let blk = n.parentElement;
      while (blk && !isBlock(blk)) blk = blk.parentElement;
      if (!groups.has(blk)) groups.set(blk, []);
      const r = document.createRange();
      for (let i = 0; i < n.textContent.length; i++) {
        r.setStart(n, i); r.setEnd(n, i + 1);
        const b = r.getBoundingClientRect();
        if (b.width === 0 && b.height === 0) continue;
        groups.get(blk).push({c: n.textContent[i], top: b.top, h: b.height});
      }
    }
    for (const [blk, chars] of groups) {
      const lines = [];
      for (const ch of chars) {
        const last = lines[lines.length - 1];
        if (last && Math.abs(ch.top - last.top) < ch.h * 0.5) last.s += ch.c;
        else lines.push({top: ch.top, s: ch.c});
      }
      if (lines.length < 2) continue;
      const txt = lines.map(l => l.s);
      const bad = [];
      txt.forEach((s, i) => {
        const core = s.replace(/[\s·,.!?()~"'…:%\-]/g, '');
        if (core.length > 0 && core.length <= 2) bad.push(`짧은 줄 '${s.trim()}'`);
        if (i > 0) {
          const prev = txt[i - 1];
          if (!/\s$/.test(prev) && !/^\s/.test(s) && /[가-힣A-Za-z0-9]$/.test(prev) && /^[가-힣A-Za-z0-9]/.test(s))
            bad.push(`낱말 중간 끊김 '${prev.trim().slice(-4)} / ${s.trim().slice(0, 4)}'`);
        }
      });
      if (bad.length) out.push({card: sec.id, lines: txt.map(s => s.trim()), bad});
    }
  }
  return out;
}
"""


def check(pptx: Path, cards_json: Path, plan: Path | None = None) -> list[dict]:
    specs = json.loads(cards_json.read_text(encoding="utf-8"))
    skip = set(json.loads(plan.read_text(encoding="utf-8")).get("slide_skip", [])) if plan else set()
    cards = [c for c in motion_hf.read_cards(pptx) if c.no not in skip]
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        motion_hf.build_project(cards, folder, specs)
        html = (folder / "index.html").read_text(encoding="utf-8")
        # 모든 카드를 한 화면씩 세로로 펼친다 (겹치지 않게)
        html = html.replace("</style>", "section.clip{position:relative!important;display:block!important;"
                            "visibility:visible!important;width:1920px;height:1080px}</style>", 1)
        (folder / "check.html").write_text(html, encoding="utf-8")
        js = folder / "check.js"
        js.write_text("const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();"
                      "const pg=await b.newPage({viewport:{width:1920,height:1080}});"
                      f"await pg.goto({json.dumps((folder / 'check.html').as_uri())});await pg.waitForTimeout(1500);"
                      f"const r=await pg.evaluate({JS.strip()});console.log(JSON.stringify(r));await b.close();}})();",
                      encoding="utf-8")
        r = subprocess.run(["node", str(js)], capture_output=True, text=True, check=True)
        res = json.loads(r.stdout.strip().splitlines()[-1])
    return res


if __name__ == "__main__":
    plan = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    res = check(Path(sys.argv[1]), Path(sys.argv[2]), plan)
    for r in res:
        print(r["card"], "|", " / ".join(r["lines"]), "→", "; ".join(r["bad"]))
    print(f"문제 {len(res)}곳")
