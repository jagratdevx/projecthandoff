import { chromium } from '@playwright/test';

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on('console', (msg) => { if (msg.type() === 'error') errors.push(`console: ${msg.text()}`); });
page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));

await page.addInitScript(() => {
  localStorage.setItem('ph_token', 'qa-token');
  const original = window.fetch.bind(window);
  const json = (body) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } });
  window.fetch = async (input, init) => {
    const url = String(input);
    if (url.includes('/api/auth/me')) return json({ user: { user_id: 'u1', name: 'QA Owner', email: 'qa@test.dev', role: 'owner', team_id: 'active-1', joined_at: '2026-01-01T00:00:00Z', status: 'active' }, team: { team_id: 'active-1', name: 'Active Event' }, subteams: [], teams: [], can_create_team: true });
    if (url.includes('/api/teams/memories')) return json([{ team_id: 'archived-1', name: 'Old Event', description: 'Completed event', status: 'archived', role: 'volunteer', state: 'observer', is_current: false, joined_at: '2026-01-01T00:00:00Z' }]);
    if (url.includes('/api/archive/archived-1/summary')) return json({ team: { team_id: 'archived-1', name: 'Old Event', description: 'Completed event', status: 'archived' }, counts: { projects: 1, tasks: 2, handovers: 1 } });
    if (url.includes('/api/archive/archived-1/activity')) return json({ items: [{ activity_id: 'a1', team_id: 'archived-1', subteam_id: '', project_id: '', task_id: '', user_id: 'u1', action: 'team.completed', description: 'event completed', timestamp: '2026-01-02T00:00:00Z', user_name: 'QA Owner' }], total: 1 });
    if (url.includes('/api/teams/archived-1/subteams')) return json([]);
    return original(input, init);
  };
});

await page.goto('http://localhost:5174/memories', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(1500);
console.log('BODY:', (await page.locator('body').innerText()).slice(0, 1200));
console.log('ERRORS:', errors);
await page.screenshot({ path: '/tmp/ph-memories-debug.png', fullPage: true });
await page.getByRole('button', { name: 'Open' }).click();
await page.waitForTimeout(1500);
console.log('DETAIL BODY:', (await page.locator('body').innerText()).slice(0, 1600));
console.log('DETAIL ERRORS:', errors);
await page.screenshot({ path: '/tmp/ph-memory-detail-debug.png', fullPage: true });
await browser.close();
