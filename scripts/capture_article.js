// 뉴스 기사 캡처 (2026-11-18): 제목부터 본문 앞부분까지 1280px 너비로 찍는다.
// 개인정보 보호: --mask 로 준 이름은 검은 막대로 가리고, 기사 안 큰 사진(인물 사진일 수 있음)은 흐리게 한다.
// 사용법: node scripts/capture_article.js URL 출력.png [--mask 이름1,이름2] [--height 900] [--mobile]
const { chromium } = require('playwright');

(async () => {
  const [url, out, ...rest] = process.argv.slice(2);
  const opt = (k, d) => { const i = rest.indexOf(k); return i >= 0 ? rest[i + 1] : d; };
  const masks = (opt('--mask', '') || '').split(',').filter(Boolean);
  const height = parseInt(opt('--height', '900'), 10);
  const mobile = rest.includes('--mobile');
  const b = await chromium.launch();
  const ctx = await b.newContext({
    viewport: mobile ? { width: 480, height: 900 } : { width: 1280, height: 1000 },
    deviceScaleFactor: 2, locale: 'ko-KR',
    userAgent: mobile
      ? 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
      : 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
  });
  const pg = await ctx.newPage();
  await pg.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await pg.waitForTimeout(3500);
  const top = await pg.evaluate((masks) => {
    // 팝업·광고·고정 헤더 치우기
    for (const el of document.querySelectorAll('*')) {
      const cs = getComputedStyle(el);
      if ((cs.position === 'fixed' || cs.position === 'sticky') && el.offsetHeight < 400) el.style.display = 'none';
    }
    document.querySelectorAll('iframe, ins, [id*="ad"], [class*="banner"]').forEach(e => { if (e.offsetHeight < 400) e.style.visibility = 'hidden'; });
    // 이름 가리기
    if (masks.length) {
      const re = new RegExp('(' + masks.map(m => m.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g');
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      const nodes = [];
      let n;
      while ((n = walker.nextNode())) if (re.test(n.textContent)) nodes.push(n);
      for (const t of nodes) {
        const span = document.createElement('span');
        span.innerHTML = t.textContent.replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(re, '<span style="background:#111;color:#111;border-radius:3px">$1</span>');
        t.replaceWith(span);
      }
    }
    // 사이드바(많이 본 뉴스·랭킹·추천)와 AI 요약 상자는 숨긴다: 다른 기사·인물 사진이 섞이고, 요약 상자에는 이름이 그대로 나온다
    document.querySelectorAll('aside, [class*="side"], [id*="side"], [class*="rank"], [class*="popular"], [class*="aside"], [class*="right"]')
      .forEach(e => { if (e.getBoundingClientRect().width < 520) e.style.visibility = 'hidden'; });
    for (const e of document.querySelectorAll('div, section')) {
      const t = e.innerText || '';
      if (t.length < 600 && /요약했어요|많이 본|실시간 급상승|랭킹|추천 기사/.test(t) && e.getBoundingClientRect().width < 520) e.style.visibility = 'hidden';
    }
    // 사진·영상은 뺀다 (인물 사진일 수 있고, 제목과 본문 글이 위로 올라와 한 화면에 담긴다)
    for (const img of document.querySelectorAll('img, video, picture, figure, iframe')) img.style.display = 'none';
    const h = [...document.querySelectorAll('h1, h2, h3')].find(e => e.innerText.trim().length > 12 && e.getBoundingClientRect().width > 300);
    if (!h) return {top: 0, left: 0, width: 0};
    const r = h.getBoundingClientRect();
    return {top: r.top + window.scrollY, left: r.left, width: r.width};
  }, masks);
  // 늦게 뜨는 요약 상자 등에도 이름이 나올 수 있어 한 번 더 가린다
  await pg.waitForTimeout(2500);
  await pg.evaluate((masks) => {
    if (!masks.length) return;
    const re = new RegExp('(' + masks.map(m => m.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'g');
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    let n;
    while ((n = walker.nextNode())) { re.lastIndex = 0; if (re.test(n.textContent) && !(n.parentElement && n.parentElement.dataset.masked)) nodes.push(n); }
    for (const t of nodes) {
      const span = document.createElement('span');
      span.innerHTML = t.textContent.replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(re, '<span data-masked="1" style="background:#111;color:#111;border-radius:3px">$1</span>');
      t.replaceWith(span);
    }
  }, masks);
  const vw = mobile ? 480 : 1280;
  // 제목이 있는 기사 칸만 (옆 사이드바의 다른 기사·인물 사진이 들어오지 않게)
  const w = top.width ? Math.min(vw, Math.max(top.width + 80, mobile ? 480 : 820)) : vw;
  const x = top.width ? Math.max(0, Math.min(top.left - 40, vw - w)) : 0;
  await pg.screenshot({ path: out, clip: { x, y: Math.max(0, top.top - 50), width: w, height }, fullPage: true });
  console.log('ok', out, 'top', Math.round(top.top), 'w', Math.round(w));
  await b.close();
})();
