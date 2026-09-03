import { chromium } from 'playwright';

const widths = [1440, 900, 520];
const url = 'http://localhost:5197/publishing/';

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });

function rectsOverlap(a, b) {
  if (!a || !b) return false;
  const left = Math.max(a.x, b.x);
  const right = Math.min(a.x + a.width, b.x + b.width);
  const top = Math.max(a.y, b.y);
  const bottom = Math.min(a.y + a.height, b.y + b.height);
  return right > left && bottom > top;
}

for (const width of widths) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(url, { waitUntil: 'networkidle' });
  // wait for the package list to actually render rows
  await page.waitForSelector('[role="listitem"] button', { timeout: 15000 });
  await page.waitForTimeout(300);

  const data = await page.evaluate(() => {
    function rect(el) {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height, top: r.top, bottom: r.bottom, left: r.left, right: r.right };
    }
    const primarySection = document.querySelector('[data-page-primary]');
    const panelHeader = primarySection ? primarySection.querySelector('header') : null;
    const firstRowButton = document.querySelector('[role="listitem"] button');
    const topline = firstRowButton ? firstRowButton.children[0] : null; // packageRowTopline span
    const platformIdentity = firstRowButton ? firstRowButton.querySelector('[data-platform-identity]') : null;
    const platformLabel = firstRowButton ? firstRowButton.querySelector('[data-platform-label]') : null;
    // status pill = topline's second child (sibling of platformIdentity)
    const statusPill = topline ? topline.children[1] : null;
    const rowId = firstRowButton ? firstRowButton.children[1] : null; // packageRowId span
    const rowMeta = firstRowButton ? firstRowButton.children[2] : null; // packageRowMeta span

    // all elements with data-platform-label text content within the whole list panel section (to check duplication)
    const allPlatformLabelsInPrimary = primarySection ? Array.from(primarySection.querySelectorAll('[data-platform-label]')).map(el => el.textContent) : [];
    const allPlatformIdentitiesInPrimary = primarySection ? primarySection.querySelectorAll('[data-platform-identity]').length : 0;

    return {
      panelHeader: rect(panelHeader),
      panelHeaderHTML: panelHeader ? panelHeader.outerHTML.slice(0, 400) : null,
      firstRowButton: rect(firstRowButton),
      firstRowButtonHTML: firstRowButton ? firstRowButton.outerHTML.slice(0, 600) : null,
      topline: rect(topline),
      platformIdentity: rect(platformIdentity),
      platformLabelText: platformLabel ? platformLabel.textContent : null,
      statusPill: rect(statusPill),
      statusPillText: statusPill ? statusPill.textContent : null,
      rowId: rect(rowId),
      rowIdText: rowId ? rowId.textContent : null,
      rowMeta: rect(rowMeta),
      allPlatformLabelsInPrimary,
      allPlatformIdentitiesInPrimary,
    };
  });

  console.log(`\n=== width ${width}px ===`);
  console.log(JSON.stringify(data, null, 2));

  console.log('--- overlap checks ---');
  console.log('panelHeader vs firstRowButton overlap:', rectsOverlap(data.panelHeader, data.firstRowButton));
  console.log('platformIdentity vs statusPill overlap:', rectsOverlap(data.platformIdentity, data.statusPill));
  console.log('platformIdentity vs rowId overlap:', rectsOverlap(data.platformIdentity, data.rowId));
  console.log('topline vs rowId overlap:', rectsOverlap(data.topline, data.rowId));

  const outPath = `/tmp/claude-0/-home-user-openclaw-media/95dc4929-2f7b-55f7-9b56-26777f0a87e1/scratchpad/publishing-${width}-before.png`;
  const primaryHandle = await page.$('[data-page-primary]');
  if (primaryHandle) {
    await primaryHandle.screenshot({ path: outPath });
    console.log('Saved panel screenshot to', outPath);
  }
  const fullPath = `/tmp/claude-0/-home-user-openclaw-media/95dc4929-2f7b-55f7-9b56-26777f0a87e1/scratchpad/publishing-${width}-full-before.png`;
  await page.screenshot({ path: fullPath, fullPage: false });
  console.log('Saved full viewport screenshot to', fullPath);

  await page.close();
}

await browser.close();
