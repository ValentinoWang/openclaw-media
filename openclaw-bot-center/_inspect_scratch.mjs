import { chromium } from 'playwright';

const url = 'http://localhost:5197/publishing/';
const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const page = await browser.newPage({ viewport: { width: 520, height: 900 } });
await page.goto(url, { waitUntil: 'networkidle' });
await page.waitForSelector('[role="listitem"] button', { timeout: 15000 });
await page.waitForTimeout(300);

const data = await page.evaluate(() => {
  function info(el) {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      tag: el.tagName,
      cls: el.className,
      text: el.textContent?.slice(0, 40),
      rect: { w: r.width, h: r.height, x: r.x, y: r.y },
      display: cs.display,
      flex: cs.flex,
      flexGrow: cs.flexGrow,
      flexShrink: cs.flexShrink,
      flexBasis: cs.flexBasis,
      minWidth: cs.minWidth,
      width: cs.width,
      justifyContent: cs.justifyContent,
      alignItems: cs.alignItems,
      flexWrap: cs.flexWrap,
      overflowWrap: cs.overflowWrap,
      wordBreak: cs.wordBreak,
      whiteSpace: cs.whiteSpace,
    };
  }
  const primarySection = document.querySelector('[data-page-primary]');
  const header = primarySection.querySelector('header'); // mg-panel-head panelHeader
  const panelHeading = header.querySelector(':scope > div'); // .panelHeading div (first child of header)
  const iconBtn = header.querySelector(':scope > button');
  const titleWrap = panelHeading.children[1]; // the div wrapping h2+p
  const h2 = titleWrap.querySelector('h2');
  const p = titleWrap.querySelector('p');
  const svgIcon = panelHeading.children[0];

  return {
    header: info(header),
    panelHeading: info(panelHeading),
    svgIcon: info(svgIcon),
    titleWrap: info(titleWrap),
    h2: info(h2),
    p: info(p),
    iconBtn: info(iconBtn),
  };
});

console.log(JSON.stringify(data, null, 2));
await browser.close();
