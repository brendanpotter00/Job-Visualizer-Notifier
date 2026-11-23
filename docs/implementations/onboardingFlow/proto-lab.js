/* Onboarding prototype lab — the first-sign-in questions, one on each screen
 * (version A; B and C were dropped on 2026-11-22). Self-contained custom element <proto-lab>. Shadow DOM keeps the product's
 * styles away from the plan runtime's styles. No network calls: the "server" is
 * an in-memory object that mirrors the plan's rules.
 *
 * The /jobs page behind the questions copies the production Recent Job Postings
 * page at both sizes the app has: phone (< 600px, the xs tokens in
 * config/responsive.ts) and desktop (a 1280 x 800 window, scaled to fit). The
 * pieces it copies: GlobalAppBar, NavigationDrawer, RecentJobPostingsPage,
 * EditCompanyPreferencesRow, RecentJobsFilters and JobListingCard. Company
 * logos come from proto-logos.js (window.PROTO_LOGOS). */
(() => {
  const CATS = [
    { slug: 'software_engineering', label: 'Software Engineering' },
    { slug: 'hardware_engineer', label: 'Hardware Engineer' },
    { slug: 'product_manager', label: 'Product Manager' },
    { slug: 'data_scientist', label: 'Data Scientist' },
    { slug: 'growth', label: 'Growth' },
    { slug: 'business_ops', label: 'Business Ops' },
  ];
  const SWE = 'software_engineering';
  const SUBS = [
    ['ai_engineering', 'AI Engineering'], ['backend', 'Backend'], ['data_engineering', 'Data Engineering'],
    ['devops_sre', 'DevOps & Site Reliability'], ['embedded_systems', 'Embedded & Low-Level Systems'],
    ['forward_deployed', 'Forward Deployed'], ['frontend', 'Frontend'], ['full_stack', 'Full Stack'],
    ['growth_engineering', 'Growth Engineering'], ['infrastructure_platform', 'Infrastructure & Platform'],
    ['ml_engineering', 'Machine Learning'], ['mobile', 'Mobile'], ['product_engineering', 'Product Engineering'],
    ['qa_testing', 'QA & Testing'], ['quantitative', 'Quantitative & Trading Systems'],
    ['robotics_autonomy', 'Robotics & Autonomy'], ['security', 'Security'],
  ].map(([slug, label]) => ({ slug, label }));
  const LEVELS = [
    ['intern', 'Intern'], ['new_grad', 'New Grad'], ['entry', 'Entry'], ['mid', 'Mid'],
    ['senior', 'Senior'], ['senior_plus', 'Staff / Principal'], ['manager', 'Manager'],
  ].map(([slug, label]) => ({ slug, label }));
  // The five presets come from the most common primary job locations in prod (2026-11-22).
  // London was dropped from the presets on request; the search still finds it.
  // 'United States' is the Location filter's existing whole-country option (job_search.py
  // _UNITED_STATES_OPTION). It matches every on-site US job, but not remote ones.
  const US = 'United States';
  const LOC_PRESETS = ['San Francisco, CA, US', 'New York, NY, US', 'Seattle, WA, US', 'Austin, TX, US', 'Remote (US)', US];
  const LOC_ALL = LOC_PRESETS.concat([
    'Sunnyvale, CA, US', 'Cupertino, CA, US', 'Redmond, WA, US', 'Mountain View, CA, US', 'San Jose, CA, US',
    'Santa Clara, CA, US', 'Palo Alto, CA, US', 'Menlo Park, CA, US', 'Los Angeles, CA, US', 'Costa Mesa, CA, US',
    'Hawthorne, CA, US', 'Boston, MA, US', 'Chicago, IL, US', 'Denver, CO, US', 'Washington, DC, US',
    'Atlanta, GA, US', 'Miami, FL, US', 'Toronto, ON, CA', 'Remote (Canada)', 'London, GB', 'Dublin, IE', 'Berlin, DE',
  ]);
  const SUB_EXPAND = { frontend: ['frontend', 'full_stack'], backend: ['backend', 'full_stack'] };
  const LEVEL_EXPAND = { entry: ['entry', 'new_grad'] };
  const label = (list, slug) => (list.find((x) => x.slug === slug) || {}).label || slug;
  const locShort = (l) => l.replace(/, US$/, '');

  // Every company here is tracked in companies.ts and has an icon in public/logos/icons.
  const J = (id, co, title, cat, sub, level, loc, ago) => ({ id, co, title, cat, sub, level, loc, ago });
  const JOBS = [
    J('stripe', 'Stripe', 'Software Engineer, Backend', SWE, 'backend', 'entry', 'San Francisco, CA, US', 4),
    J('figma', 'Figma', 'Software Engineer, Full Stack', SWE, 'full_stack', 'mid', 'San Francisco, CA, US', 9),
    J('notion', 'Notion', 'Frontend Engineer', SWE, 'frontend', 'entry', 'New York, NY, US', 13),
    J('anthropic', 'Anthropic', 'Machine Learning Engineer', SWE, 'ml_engineering', 'senior', 'San Francisco, CA, US', 18),
    J('databricks', 'Databricks', 'Software Engineer, New Grad', SWE, 'backend', 'new_grad', 'San Francisco, CA, US', 22),
    J('cloudflare', 'Cloudflare', 'Systems Engineer, Infrastructure', SWE, 'infrastructure_platform', 'mid', 'Austin, TX, US', 27),
    J('robinhood', 'Robinhood', 'iOS Engineer', SWE, 'mobile', 'entry', 'New York, NY, US', 31),
    J('airbnb', 'Airbnb', 'Product Manager, Payments', 'product_manager', null, 'mid', 'San Francisco, CA, US', 35),
    J('lyft', 'Lyft', 'Data Scientist, Pricing', 'data_scientist', null, 'entry', 'Seattle, WA, US', 41),
    J('andurilindustries', 'Anduril', 'RF Hardware Engineer', 'hardware_engineer', null, 'mid', 'Costa Mesa, CA, US', 44),
    J('vercel', 'Vercel', 'Software Engineer, Full Stack', SWE, 'full_stack', 'entry', 'Remote (US)', 48),
    J('datadog', 'Datadog', 'Site Reliability Engineer', SWE, 'devops_sre', 'mid', 'New York, NY, US', 53),
    J('coinbase', 'Coinbase', 'Security Engineer', SWE, 'security', 'senior', 'Remote (US)', 58),
    J('spotify', 'Spotify', 'Backend Engineer', SWE, 'backend', 'mid', 'London, GB', 63),
    J('pinterest', 'Pinterest', 'Software Engineer Intern', SWE, 'full_stack', 'intern', 'San Francisco, CA, US', 70),
    J('janestreet', 'Jane Street', 'Software Engineer', SWE, 'quantitative', 'new_grad', 'New York, NY, US', 76),
    J('waymo', 'Waymo', 'Software Engineer, Perception', SWE, 'robotics_autonomy', 'senior', 'Mountain View, CA, US', 82),
    J('brex', 'Brex', 'Growth Marketing Manager', 'growth', null, 'mid', 'New York, NY, US', 88),
    J('instacart', 'Instacart', 'Business Operations Associate', 'business_ops', null, 'entry', 'San Francisco, CA, US', 95),
    J('openai', 'OpenAI', 'AI Engineer, Applied', SWE, 'ai_engineering', 'mid', 'San Francisco, CA, US', 101),
    J('discord', 'Discord', 'Software Engineer, Backend', SWE, 'backend', 'entry', 'Remote (US)', 108),
    J('reddit', 'Reddit', 'Data Engineer', SWE, 'data_engineering', 'entry', 'Remote (US)', 115),
    J('twilio', 'Twilio', 'Software Engineer, Frontend', SWE, 'frontend', 'new_grad', 'Remote (US)', 122),
    J('palantir', 'Palantir', 'Forward Deployed Software Engineer', SWE, 'forward_deployed', 'entry', 'New York, NY, US', 130),
    J('roblox', 'Roblox', 'Software Engineer, Growth', SWE, 'growth_engineering', 'senior', 'San Francisco, CA, US', 138),
    J('mongodb', 'MongoDB', 'Product Engineer', SWE, 'product_engineering', 'mid', 'New York, NY, US', 146),
    J('spacex', 'SpaceX', 'Embedded Software Engineer', SWE, 'embedded_systems', 'entry', 'Hawthorne, CA, US', 153),
    J('neuralink', 'Neuralink', 'QA Engineer, Implant Software', SWE, 'qa_testing', 'mid', 'Austin, TX, US', 160),
    J('dropbox', 'Dropbox', 'Staff Software Engineer, Platform', SWE, 'infrastructure_platform', 'senior_plus', 'Remote (US)', 168),
    J('doordashusa', 'Doordash', 'Engineering Manager, Logistics', SWE, 'backend', 'manager', 'San Francisco, CA, US', 175),
    J('optiver', 'Optiver', 'Data Scientist', 'data_scientist', null, 'new_grad', 'Chicago, IL, US', 182),
    J('figureai', 'Figure AI', 'Hardware Engineer, Actuators', 'hardware_engineer', null, 'entry', 'Sunnyvale, CA, US', 190),
  ];

  const ABOUT = 'One question on each screen. Skip sits with 1/3 above the step bar. Back and Continue sit at the bottom, and Back is disabled on question 1. A full page at every size, with nothing behind it. When it closes, Recent Job Postings shows the answers in its own filters.';
  const STEPS = 3;
  const DESK_W = 1280; const DESK_H = 800;

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  // date-fns formatDistanceToNow(..., { addSuffix: true }), as useJobMetadata prints it.
  const postedAgo = (m) => (m < 1 ? 'less than a minute ago' : m < 45 ? `${m} minute${m === 1 ? '' : 's'} ago`
    : m < 90 ? 'about 1 hour ago' : `about ${Math.round(m / 60)} hours ago`);
  const clock = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // MUI icon paths, copied from @mui/icons-material.
  const mi = (paths, s = 24) => `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="currentColor" aria-hidden="true">${[].concat(paths).map((d) => `<path d="${d}"/>`).join('')}</svg>`;
  const I = {
    check: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3 8.5l3.2 3L13 4.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    chev: '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    search: '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10.5 10.5L14 14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>',
    g: '<svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true"><path fill="#4285F4" d="M17.6 9.2c0-.6-.1-1.2-.2-1.8H9v3.4h4.8a4.1 4.1 0 0 1-1.8 2.7v2.2h2.9c1.7-1.6 2.7-3.9 2.7-6.5z"/><path fill="#34A853" d="M9 18c2.4 0 4.5-.8 6-2.2l-2.9-2.2c-.8.5-1.9.9-3.1.9-2.4 0-4.4-1.6-5.1-3.8H.9v2.3A9 9 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.9 10.7a5.4 5.4 0 0 1 0-3.4V5H.9a9 9 0 0 0 0 8l3-2.3z"/><path fill="#EA4335" d="M9 3.6c1.3 0 2.5.5 3.5 1.4l2.6-2.6A9 9 0 0 0 .9 5l3 2.3C4.6 5.2 6.6 3.6 9 3.6z"/></svg>',
    // SidebarToggleButton.tsx
    side: '<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"><rect x="3" y="4.75" width="18" height="14.5" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M9.25 4.75v14.5" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>',
    drop: mi('m7 10 5 5 5-5z'),
    cancel: mi('M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2m5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12z', 16),
    ext: mi(['M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3z'], 14),
    schedule: mi(['M11.99 2C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2M12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8', 'M12.5 7H11v6l5.25 3.15.75-1.23-4.5-2.67z']),
    trend: mi('m16 6 2.29 2.29-4.88 4.88-4-4L2 16.59 3.41 18l6-6 4 4 6.3-6.29L22 12V6z'),
    filter: mi('M4.25 5.66c.1.13 5.74 7.33 5.74 7.33V19c0 .55.45 1 1.01 1h2.01c.55 0 1.01-.45 1.01-1v-6.02s5.49-7.02 5.75-7.34S20 5 20 5c0-.55-.45-1-1.01-1H5.01C4.4 4 4 4.48 4 5c0 .2.06.44.25.66'),
    addbiz: mi(['M15 17h2v-3h1v-2l-1-5H2l-1 5v2h1v6h9v-6h4zm-6 1H4v-4h5zM2 4h15v2H2z', 'M20 18v-3h-2v3h-3v2h3v3h2v-3h3v-2z']),
    biz: mi('M12 7V3H2v18h20V7zM6 19H4v-2h2zm0-4H4v-2h2zm0-4H4V9h2zm0-4H4V5h2zm4 12H8v-2h2zm0-4H8v-2h2zm0-4H8V9h2zm0-4H8V5h2zm10 12h-8v-2h2v-2h-2v-2h2v-2h-2V9h8zm-2-8h-2v2h2zm0 4h-2v2h2z'),
    thumb: mi('M1 21h4V9H1zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73z'),
    info: mi('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2m1 15h-2v-6h2zm0-8h-2V7h2z'),
    acct: mi('M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2m0 4c1.93 0 3.5 1.57 3.5 3.5S13.93 13 12 13s-3.5-1.57-3.5-3.5S10.07 6 12 6m0 14c-2.03 0-4.43-.82-6.14-2.88C7.55 15.8 9.68 15 12 15s4.45.8 6.14 2.12C16.43 19.18 14.03 20 12 20'),
  };

  const CSS = `
  :host { display: block; --ink:#000; --paper:#fff; --mist:#f5f5f5; --rule:#e0e0e0; --edge:#757575; --muted:#666; --bone:#F2EEE9; --signal:#2F8F3F;
    --pl-ink: var(--ink-p, #141413); }
  * { box-sizing: border-box; }
  .wrap { display: grid; grid-template-columns: 395px minmax(0, 1fr); grid-template-areas: "phone ctl" "phone side"; grid-template-rows: auto 1fr; column-gap: 28px; align-items: start; }
  .wrap > .phone, .wrap > .deskframe { grid-area: phone; } .wrap > .side { grid-area: side; } .wrap > .side.ctl { grid-area: ctl; }
  .wrap.desk { grid-template-columns: minmax(0, 1fr); grid-template-areas: "ctl" "phone" "side"; grid-template-rows: auto; }
  .wrap.desk > .side.ctl { margin: 0 0 16px; }
  .wrap.desk > .side.ctl .grp { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); column-gap: 20px; }
  .wrap.desk > .side.ctl .grp > * { grid-column: 2; } .wrap.desk > .side.ctl .grp > .dev { grid-column: 1; grid-row: 1 / span 6; }
  .wrap.desk > .side:not(.ctl) { margin-top: 20px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
  .wrap.desk > .side:not(.ctl) .grp { margin: 0; }
  @media (max-width: 860px) {
    .wrap { grid-template-columns: minmax(0, 1fr); grid-template-areas: "ctl" "phone" "side"; grid-template-rows: auto; } .wrap > .side { margin-top: 20px; } .wrap > .side.ctl { margin: 0 0 16px; }
    .wrap.desk > .side.ctl .grp { display: block; } .wrap.desk > .side:not(.ctl) { display: block; } .wrap.desk > .side:not(.ctl) .grp { margin-bottom: 14px; }
  }

  /* ── the phone: product tokens only ── */
  .phone { width: 395px; max-width: 100%; border-radius: 40px; background: #1b1b1b; padding: 10px; box-shadow: 0 0 0 1px rgba(0,0,0,.25); justify-self: center; position: sticky; top: 16px; }
  @media (max-width: 860px) { .phone { position: static; } }
  @media (max-width: 440px) { .phone { padding: 0; border-radius: 14px; background: transparent; box-shadow: 0 0 0 1px rgba(127,127,127,.35); } }
  .screen { position: relative; height: 720px; border-radius: 30px; overflow: hidden; background: var(--paper); color: var(--ink);
    font: 400 16px/1.5 "Helvetica", "Arial", sans-serif; display: flex; flex-direction: column; isolation: isolate; }
  @media (max-width: 440px) { .screen { border-radius: 14px; height: 680px; } }
  .screen :focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
  .screen .bar :focus-visible, .screen .appbar :focus-visible { outline-color: var(--bone); }

  /* ── the desktop: a 1280 x 800 window, scaled to the width of the lab ── */
  .deskframe { width: 100%; min-width: 0; border-radius: 10px; overflow: hidden; background: #e6e6e6; box-shadow: 0 0 0 1px rgba(0,0,0,.22), 0 10px 30px rgba(0,0,0,.12); }
  .dbar { height: 32px; display: flex; align-items: center; gap: 7px; padding: 0 12px; border-bottom: 1px solid #cfcfcf; }
  .dbar i { width: 11px; height: 11px; border-radius: 50%; background: #c4c4c4; }
  .dbar .url { margin-left: 10px; flex: 1; max-width: 420px; height: 22px; border-radius: 6px; background: #fff; color: #555; font: 12px/22px system-ui, sans-serif; padding: 0 10px; white-space: nowrap; overflow: hidden; }
  .desk-vp { position: relative; height: calc(${DESK_H}px * var(--s, 0.8)); overflow: hidden; background: #fff; }
  .screen.desk { width: ${DESK_W}px; height: ${DESK_H}px; border-radius: 0; transform: scale(var(--s, 0.8)); transform-origin: 0 0; }

  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .bar { height: 56px; flex: none; background: #000; color: var(--bone); display: flex; align-items: center; gap: 10px; padding: 0 8px 0 16px; }
  .mark { font: 700 20px/1 "Infra Mono", ui-monospace, Menlo, monospace; letter-spacing: -0.03em; display: inline-flex; align-items: center; gap: 8px; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--signal); box-shadow: 0 0 8px rgba(47,143,63,.6); display: inline-block; }
  .bar .grow, .appbar .grow { flex: 1; }
  .body { flex: 1; overflow-y: auto; overscroll-behavior: contain; padding: 20px 16px 24px; scroll-padding-bottom: 96px; }
  .foot { flex: none; border-top: 1px solid var(--rule); background: var(--paper); padding: 12px 16px 16px; display: flex; gap: 10px; }
  h1, h2, h3 { font-weight: 500; letter-spacing: -0.03em; line-height: 1.15; margin: 0; }
  /* The question has no subtitle; the options start right under it. */
  .q { font-size: 26px; margin: 6px 0 20px; outline: none; }
  /* The step counter: "1/3" over a bar that fills one third for each question. */
  .prog-n { font-size: 14px; line-height: 1; color: var(--muted); font-variant-numeric: tabular-nums; }
  .prog-track { display: block; height: 4px; margin-top: 4px; border-radius: 2px; background: var(--rule); overflow: hidden; }
  .prog-fill { display: block; height: 100%; width: var(--to); border-radius: 2px; background: var(--ink); animation: fill .3s ease-out; }
  @keyframes fill { from { width: var(--from); } to { width: var(--to); } }
  .btn { min-height: 48px; padding: 0 18px; border-radius: 8px; font: 500 16px/1 inherit; font-family: inherit; cursor: pointer; border: 1px solid var(--ink); background: var(--paper); color: var(--ink); display: inline-flex; align-items: center; justify-content: center; gap: 10px; }
  .btn.pri { background: var(--ink); color: #fff; flex: 1; }
  .btn.pri:hover { background: #333; }
  .btn.wide { width: 100%; }
  .btn:active { transform: translateY(1px); }
  .linkbtn { border: 0; background: none; color: var(--ink); text-decoration: underline; text-underline-offset: 3px; font: inherit; padding: 10px 4px; min-height: 44px; cursor: pointer; }

  /* role rows: a checkbox list; Software Engineering reveals its specialties in place */
  .rows { border-top: 1px solid var(--rule); margin: 0; padding: 0; }
  .row { display: flex; align-items: center; gap: 14px; min-height: 56px; padding: 0 4px; border-bottom: 1px solid var(--rule); cursor: pointer; position: relative; }
  .row input { position: absolute; opacity: 0; width: 100%; height: 100%; left: 0; top: 0; margin: 0; cursor: pointer; }
  .box { width: 22px; height: 22px; flex: none; border: 2px solid var(--edge); border-radius: 4px; display: inline-flex; align-items: center; justify-content: center; color: #fff; }
  .row input:checked ~ .box { background: var(--ink); border-color: var(--ink); }
  .row input:not(:checked) ~ .box svg { visibility: hidden; }
  .row input:focus-visible ~ .box { outline: 2px solid var(--ink); outline-offset: 3px; }
  .row .lbl { flex: 1; font-size: 17px; }
  .row .meta { color: var(--muted); font-size: 14px; display: inline-flex; align-items: center; gap: 4px; }
  .row .meta svg { transition: transform .18s ease; }
  .row.open .meta svg { transform: rotate(180deg); }
  .reveal { border-bottom: 1px solid var(--rule); padding: 12px 0 16px 40px; position: relative; }
  .reveal::before { content: ""; position: absolute; left: 14px; top: 0; bottom: 14px; border-left: 2px solid var(--ink); }
  .reveal .sub { font-size: 14px; color: var(--muted); margin: 0 0 10px; }
  .reveal .chips { gap: 6px; }
  .reveal .chip { min-height: 40px; padding: 0 20px; font-size: 14px; }
  .reveal .chip:has(input:checked) { padding-left: 4px; }
  .anim .reveal { animation: drop .2s ease-out; }
  @keyframes drop { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

  /* chips: native checkboxes drawn as chips */
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 0; padding: 0; border: 0; }
  /* A chip keeps one width, picked or not: the check (12px + 4px gap) takes the place of left padding,
     so a tap never pushes the next chip to a new line. */
  .chip { position: relative; display: inline-flex; align-items: center; gap: 4px; min-height: 44px; padding: 0 24px; border: 1px solid var(--edge); border-radius: 4px; background: var(--paper); font-size: 15px; cursor: pointer; user-select: none; }
  .chip input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
  .chip svg { display: none; width: 12px; height: 12px; flex: none; }
  .chip:has(input:checked) { background: var(--ink); border-color: var(--ink); color: #fff; padding-left: 8px; }
  .chip:has(input:checked) svg { display: inline; }
  .chip:has(input:focus-visible) { outline: 2px solid var(--ink); outline-offset: 2px; }
  .chip:hover { border-color: var(--ink); }
  fieldset { border: 0; margin: 0; padding: 0; min-width: 0; }
  legend { padding: 0; width: 100%; }

  .search { margin-top: 14px; position: relative; }
  .search label { display: block; font-size: 15px; margin-bottom: 6px; }
  .search .field { display: flex; align-items: center; gap: 8px; border: 1px solid var(--edge); border-radius: 8px; padding: 0 12px; min-height: 48px; }
  .search .field:focus-within { outline: 2px solid var(--ink); outline-offset: 1px; }
  .search input { border: 0; outline: 0; font: inherit; flex: 1; min-width: 0; background: transparent; color: var(--ink); }
  .sugs { list-style: none; margin: 6px 0 0; padding: 0; border: 1px solid var(--rule); border-radius: 8px; overflow: hidden; }
  .sugs button { width: 100%; text-align: left; min-height: 44px; padding: 0 12px; border: 0; border-top: 1px solid var(--rule); background: var(--paper); font: inherit; cursor: pointer; color: var(--ink); }
  .sugs li:first-child button { border-top: 0; }
  .sugs button:hover, .sugs button:focus-visible { background: var(--mist); }
  .sugs .none { padding: 10px 12px; color: var(--muted); font-size: 15px; }

  /* sign-in + interstitial */
  .signin { padding: 28px 20px; display: flex; flex-direction: column; gap: 14px; flex: 1; }
  .signin .bigmark { font: 700 22px/1 "Infra Mono", ui-monospace, Menlo, monospace; letter-spacing: -0.03em; margin-bottom: 36px; display: inline-flex; gap: 10px; align-items: center; }
  .signin h1 { font-size: 34px; margin-bottom: 4px; }
  .signin p { margin: 0 0 10px; color: var(--muted); }
  .signin .small { font-size: 14px; color: var(--muted); margin-top: 6px; }
  .si-desk { display: flex; justify-content: center; align-items: flex-start; padding-top: 72px; }
  .si-desk .signin { flex: none; width: 440px; border: 1px solid var(--rule); border-radius: 8px; padding: 32px; }
  .wait { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--muted); }

  /* ── the Recent Job Postings page, copied from production ──
     Phone values are the xs tokens in config/responsive.ts; .desk values are the sm tokens. */
  .pg { flex: 1; min-height: 0; display: flex; flex-direction: column; }
  .pg-row { flex: 1; min-height: 0; display: flex; }
  .appbar { height: 56px; flex: none; background: #000; color: #fff; display: flex; align-items: center; padding: 0 16px; position: relative; z-index: 3;
    box-shadow: 0 2px 4px -1px rgba(0,0,0,.2), 0 4px 5px 0 rgba(0,0,0,.14), 0 1px 10px 0 rgba(0,0,0,.12); }
  .screen.desk .appbar { height: 64px; padding: 0 24px; }
  .appbar .tog { width: 44px; height: 44px; margin: 0 16px 0 -12px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: #fff; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
  .appbar .tog:hover, .appbar .av-btn:hover { background: rgba(255,255,255,.08); }
  .appbar .wm { display: inline-flex; align-items: center; gap: 14px; color: var(--bone); font: 700 20px/1 "Infra Mono", ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: -0.03em; }
  .appbar .wm .full { display: none; } .screen.desk .appbar .wm .full { display: inline; }
  .appbar .wm .one { font-size: 22px; display: inline-flex; align-items: center; gap: 6px; }
  .appbar .av-btn { width: 44px; height: 44px; padding: 0; border: 0; border-radius: 50%; background: transparent; display: inline-flex; align-items: center; justify-content: center; cursor: pointer; }
  .appbar .av { width: 32px; height: 32px; border-radius: 50%; background: #7e57c2; color: #fff; font: 400 14px/32px "Helvetica", "Arial", sans-serif; text-align: center; }
  /* NavigationDrawer is MUI's mini-variant drawer, which sets white-space: nowrap. */
  .drawer { width: 240px; flex: none; background: var(--mist); border-right: 1px solid var(--rule); display: flex; flex-direction: column; padding: 0 0 8px; white-space: nowrap; overflow: hidden; }
  .drawer .sh { padding: 10px 20px 4px; font-size: 11px; letter-spacing: .18em; font-weight: 700; color: var(--muted); }
  .drawer .it { display: flex; align-items: center; gap: 24px; min-height: 48px; padding: 0 20px; border: 0; background: transparent; width: 100%; text-align: left; font: 400 16px/1.5 "Helvetica", "Arial", sans-serif; color: #000; cursor: pointer; }
  .drawer .it:first-of-type { margin-top: 8px; }
  .drawer .it svg { color: rgba(0,0,0,.54); flex: none; }
  .drawer .it:hover { background: rgba(0,0,0,.04); }
  .drawer .it.on { background: rgba(0,0,0,.08); }
  .drawer hr { border: 0; border-top: 1px solid var(--rule); margin: 8px 0; width: 100%; }
  .drawer .grow { flex: 1; }
  .screen .pg-main { flex: 1; min-width: 0; padding: 16px; }
  .screen.desk .pg-main { padding: 32px 24px; }
  .pg-h1 { font: 600 24px/1.3 "Helvetica", "Arial", sans-serif; letter-spacing: 0; margin: 0 0 16px; outline: none; }
  .screen.desk .pg-h1 { font-size: 28px; }
  .flt { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
  .screen.desk .flt { gap: 16px; margin-bottom: 24px; }
  .flt .frow { display: flex; flex-direction: column; gap: 8px; }
  .screen.desk .flt .frow { flex-direction: row; gap: 16px; align-items: flex-start; }
  .fld { position: relative; display: flex; align-items: center; flex-wrap: wrap; gap: 4px; width: 100%; min-height: 36px; padding: 5px 34px 5px 14px; border: 1px solid rgba(0,0,0,.23); border-radius: 8px; background: transparent; color: #000; font: 400 13px/1.4375 "Helvetica", "Arial", sans-serif; text-align: left; cursor: pointer; }
  .screen.desk .fld { min-height: 44px; font-size: 16px; padding: 8px 34px 8px 14px; width: auto; }
  .screen.desk .fld.kw { width: 100%; }
  .screen.desk .fld.w150 { min-width: 150px; } .screen.desk .fld.w170 { min-width: 170px; } .screen.desk .fld.w240 { min-width: 240px; }
  .fld:hover { border-color: #000; }
  .fld .flab { color: rgba(0,0,0,.6); }
  .fld.up .flab { position: absolute; left: 9px; top: 0; transform: translateY(-50%); padding: 0 5px; background: #fff; font-size: 9.75px; line-height: 1; }
  .screen.desk .fld.up .flab { font-size: 12px; }
  .fld .fval { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }
  .screen.desk .fld .fval { max-width: 260px; }
  .fld > svg { position: absolute; right: 7px; top: 50%; transform: translateY(-50%); color: rgba(0,0,0,.54); }
  .fld .tag { display: inline-flex; align-items: center; gap: 3px; height: 24px; padding: 0 3px 0 8px; border-radius: 4px; background: rgba(0,0,0,.08); font-size: 13px; white-space: nowrap; }
  .fld .tag svg { color: rgba(0,0,0,.26); }
  .fld .ph { color: rgba(0,0,0,.42); padding-left: 2px; }
  .rst { min-height: 36px; padding: 0 12px; border: 1px solid rgba(0,0,0,.5); border-radius: 8px; background: transparent; color: #000; font: 500 12px/1.75 "Helvetica", "Arial", sans-serif; cursor: pointer; }
  .screen.desk .rst { min-height: 44px; padding: 0 16px; font-size: 13px; }
  .rst:hover { background: rgba(0,0,0,.04); border-color: #000; }
  /* After the questions: a toast at the top right, under the top bar (MUI Snackbar, anchorOrigin top-right).
     A check and a link to /saved-filters. It hides after 6 s; hover or focus keeps it open. */
  .snack { position: absolute; z-index: 20; top: 64px; right: 12px; max-width: calc(100% - 24px); display: inline-flex; align-items: center; gap: 8px;
    padding: 2px 4px 2px 14px; border-radius: 8px; background: #000; color: #fff; font-size: 14px; line-height: 1.45;
    box-shadow: 0 3px 5px -1px rgba(0,0,0,.2), 0 6px 10px 0 rgba(0,0,0,.14), 0 1px 18px 0 rgba(0,0,0,.12); }
  .screen.desk .snack { top: 80px; right: 24px; }
  .snack.enter { animation: snackin .22s ease-out; }
  @keyframes snackin { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: none; } }
  .snack .ok { display: inline-flex; color: #4cbb5e; flex: none; }
  .snack .go { min-height: 40px; display: inline-flex; align-items: center; border: 0; background: none; padding: 0; font: 500 14px/1.45 "Helvetica", "Arial", sans-serif; color: #fff; text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
  .snack .x { border: 0; background: none; font-size: 20px; line-height: 1; min-width: 40px; min-height: 40px; cursor: pointer; color: #fff; border-radius: 8px; }
  .snack .x:hover { background: rgba(255,255,255,.14); }
  .snack :focus-visible { outline-color: #fff; }
  @media (prefers-reduced-motion: reduce) { .snack.enter { animation: none; } }
  .jc { background: var(--mist); border: 1px solid var(--rule); border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.12); margin-bottom: 8px; cursor: pointer; }
  .jc:hover { background: rgba(0,0,0,.04); box-shadow: 0 2px 8px rgba(0,0,0,.15); }
  .screen.desk .jc { margin-bottom: 16px; }
  .jc-c { padding: 8px; display: flex; flex-direction: column; gap: 2px; }
  .screen.desk .jc-c { padding: 16px 16px 24px; gap: 8px; }
  .jc-h { display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; align-items: flex-start; }
  .jc-hl { flex: 1 1 0; min-width: 0; display: flex; align-items: center; gap: 12px; }
  .screen.desk .jc-hl { flex-basis: 160px; }
  .logo { width: 32px; height: 32px; flex: none; border: 1px solid var(--rule); border-radius: 8px; background: var(--mist); overflow: hidden; display: flex; align-items: center; justify-content: center; font-weight: 700; }
  .screen.desk .logo { width: 44px; height: 44px; }
  .logo img { width: 100%; height: 100%; object-fit: contain; display: block; }
  .jc-tx { min-width: 0; overflow-wrap: anywhere; }
  .jc-co { font: 700 14px/1.57 "Helvetica", "Arial", sans-serif; color: var(--muted); }
  .jc-t { font: 600 15px/1.5 "Helvetica", "Arial", sans-serif; letter-spacing: 0; color: #000; }
  .screen.desk .jc-t { font-size: 16px; }
  .jc-ap { flex: none; min-height: 36px; padding: 4px 10px; border: 0; border-radius: 16px; background: #000; color: #fff; font: 500 12px/1.75 "Helvetica", "Arial", sans-serif; cursor: pointer;
    box-shadow: 0 3px 1px -2px rgba(0,0,0,.2), 0 2px 2px 0 rgba(0,0,0,.14), 0 1px 5px 0 rgba(0,0,0,.12); }
  .screen.desk .jc-ap { min-height: 44px; padding: 4px 16px; font-size: 13px; }
  .jc-ap:hover { background: #212121; }
  .crow { display: flex; flex-wrap: wrap; gap: 8px; }
  .mc { display: inline-flex; align-items: center; height: 20px; padding: 0 5px; border-radius: 4px; font-size: 10px; color: #000; white-space: nowrap; }
  .mc.o { border: 1px solid #bdbdbd; } .mc.f { background: rgba(0,0,0,.08); }
  .screen.desk .mc { height: 24px; font-size: 13px; padding: 0 8px; } .screen.desk .mc.o { padding: 0 7px; }
  .dm { display: inline-flex; align-items: center; gap: 4px; width: fit-content; padding: 0; border: 0; background: none; font: 400 12px/1.66 "Helvetica", "Arial", sans-serif; letter-spacing: .03333em; color: #000; cursor: pointer; }
  .dm:hover { text-decoration: underline; }
  .posted { font-size: 12px; line-height: 1.66; letter-spacing: .03333em; color: var(--muted); }
  .pg-empty { text-align: center; padding: 32px 0; } .pg-empty b { display: block; font-weight: 600; margin-bottom: 4px; } .pg-empty span { font-size: 14px; color: var(--muted); }
  .pg-end { text-align: center; padding: 24px 0 8px; margin: 0; font-size: 14px; color: var(--muted); }
  .menu { position: absolute; right: 10px; top: 58px; background: var(--paper); border: 1px solid var(--rule); border-radius: 8px; box-shadow: 0 6px 18px rgba(0,0,0,.14); z-index: 5; min-width: 180px; }
  .screen.desk .menu { right: 24px; top: 62px; }
  .menu button { display: block; width: 100%; text-align: left; border: 0; background: none; min-height: 44px; padding: 0 14px; font: inherit; color: var(--ink); cursor: pointer; }
  .menu button + button { border-top: 1px solid var(--rule); }
  .toast { position: absolute; left: 16px; right: 16px; bottom: 18px; background: #000; color: #fff; border-radius: 8px; padding: 12px 14px; font-size: 15px; z-index: 30; }
  .screen.desk .toast { left: 50%; right: auto; transform: translateX(-50%); width: 520px; }

  /* The questions are one full page at every size. On a desktop the content is one 560px column. */
  .col { width: 100%; }
  .screen.desk .col { max-width: 560px; margin: 0 auto; }
  .screen.desk .bar { height: 64px; padding: 0 24px; }
  /* Back and Skip are navigation, so they sit with the step bar, in one row that never scrolls away.
     Back keeps its space on question 1 (hidden, not removed), so the bar does not jump on question 2. */
  /* Two lines: 1/3 and Skip, then the bar across the full column. */
  .qnav { flex: none; padding: 6px 16px 0; }
  .qline { display: flex; align-items: center; gap: 2px; min-height: 44px; }
  .qline .grow { flex: 1; }
  .screen.desk .qnav { padding: 24px 24px 0; }
  .navbtn { flex: none; display: inline-flex; align-items: center; min-height: 44px; border: 0; border-radius: 8px; background: none; color: var(--ink); font: 500 15px/1 "Helvetica", "Arial", sans-serif; cursor: pointer; }
  .navbtn.skip { padding: 0 6px 0 10px; margin-right: -6px; }
  .navbtn:hover { background: var(--mist); }
  .qbody { padding: 16px 16px 24px; }
  .screen.desk .qbody { padding: 24px 24px 32px; }
  /* One button at the bottom. Its top rule shows only while the question scrolls under it. */
  .qfoot { border-top-color: transparent; transition: border-color .15s; }
  .qfoot.edge { border-top-color: var(--rule); }
  .qfoot .col { display: flex; gap: 10px; }
  /* Back sits next to Continue. On question 1 it shows but is disabled, so the row never changes shape. */
  .btn.back { flex: none; min-width: 96px; }
  .btn[disabled] { border-color: rgba(0,0,0,.12); color: rgba(0,0,0,.38); cursor: default; transform: none; }
  .screen.desk .qfoot { padding: 14px 24px 22px; }
  .screen.desk .q { font-size: 30px; }
  @media (prefers-reduced-motion: reduce) { .anim .reveal, .prog-fill, .row .meta svg, .qfoot { animation: none !important; transition: none !important; } }

  /* ── the side panel: plan-runtime tokens, so it follows light and dark ── */
  .side { font: 430 15px/1.55 var(--sans, system-ui, sans-serif); color: var(--ink, #141413); min-width: 0; }
  .side h3 { font-size: 15px; font-weight: 600; margin: 0 0 8px; letter-spacing: 0; line-height: 1.4; }
  .side .grp { border: 1px solid var(--line, rgba(0,0,0,.15)); border-radius: 12px; background: var(--card, #fff); padding: 14px; margin-bottom: 14px; }
  .side .state { margin-top: 10px; }
  .vers { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; margin: 0 0 10px; }
  .vers.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .vers label { position: relative; border: 1px solid var(--line, #ccc); border-radius: 8px; padding: 8px 10px; cursor: pointer; display: block; min-height: 44px; }
  .vers label b { display: block; font-size: 13px; color: var(--ink-3, #666); font-weight: 550; }
  .vers label span { display: block; font-weight: 600; font-size: 15px; }
  .vers input { position: absolute; opacity: 0; inset: 0; margin: 0; cursor: pointer; }
  .vers label:has(input:checked) { border-color: var(--ink, #000); box-shadow: inset 0 0 0 1px var(--ink, #000); }
  .vers label:has(input:focus-visible) { outline: 2px solid var(--ink, #000); outline-offset: 2px; }
  .side p { margin: 0 0 8px; color: var(--ink-2, #333); }
  .acts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
  .sbtn { min-height: 40px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--line, #ccc); background: var(--paper, #fff); color: var(--ink, #000); font: 550 14px/1 var(--sans, system-ui); cursor: pointer; }
  .sbtn:hover { border-color: var(--ink, #000); }
  .sbtn:focus-visible { outline: 2px solid var(--ink, #000); outline-offset: 2px; }
  .sbtn[disabled] { opacity: .45; cursor: default; }
  .state { font-weight: 600; }
  .state .ok { color: var(--green, #2c7a39); }
  .state .wait { color: var(--amber, #946410); display: inline; }
  pre.db { font: 12.5px/1.5 var(--mono, ui-monospace, monospace); background: var(--sunk, #f0eee6); border-radius: 8px; padding: 10px 12px; margin: 0; white-space: pre-wrap; word-break: break-word; }
  pre.db .k { color: var(--ink-3, #666); }
  pre.db .null { color: var(--amber, #946410); }
  pre.db .set { color: var(--green, #2c7a39); }
  ol.log { margin: 0; padding: 0; list-style: none; font: 12.5px/1.45 var(--mono, ui-monospace, monospace); max-height: 190px; overflow: auto; }
  ol.log li { padding: 5px 0; border-top: 1px solid var(--line-2, rgba(0,0,0,.08)); }
  ol.log li:first-child { border-top: 0; }
  ol.log .t { color: var(--ink-3, #777); }
  ol.log .r { color: var(--ink-2, #333); display: block; padding-left: 12px; }
  table.runs { width: 100%; border-collapse: collapse; font-size: 13.5px; }
  table.runs th, table.runs td { text-align: left; padding: 5px 6px 5px 0; border-top: 1px solid var(--line-2, rgba(0,0,0,.08)); vertical-align: top; }
  table.runs th { font-weight: 550; color: var(--ink-3, #666); border-top: 0; }
  table.runs td.n { font-variant-numeric: tabular-nums; }
  .empty-runs { color: var(--ink-3, #777); font-size: 14px; }
  `;

  const emptyDraft = () => ({ cats: new Set(), subs: new Set(), levels: new Set(), locs: new Set() });
  const toast = (msg) => ` data-act="toast" data-msg="${esc(msg)}"`;

  class ProtoLab extends HTMLElement {
    connectedCallback() {
      if (this._root) return;
      this._root = this.attachShadow({ mode: 'open' });
      this.S = {
        device: 'phone', account: null, screen: 'signin', step: 0, fromStep: null, draft: emptyDraft(), q: '',
        enter: false, justDone: false, menu: false, toast: '', run: null,
        runs: [], log: [], runNo: 0, announce: '',
      };
      this._root.addEventListener('click', (e) => this.onClick(e));
      this._root.addEventListener('change', (e) => this.onChange(e));
      this._root.addEventListener('input', (e) => this.onInput(e));
      this._root.addEventListener('keydown', (e) => this.onKey(e));
      if (window.ResizeObserver) { this._ro = new ResizeObserver(() => this.fit()); this._ro.observe(this); }
      this.render({ first: true });
    }
    get desk() { return this.S.device === 'desktop'; }

    /* ── the fake server: mirrors the plan's rules ── */
    req(line, result) { this.S.log.unshift({ t: clock(), line, result }); this.S.log = this.S.log.slice(0, 12); }
    getUser() {
      const S = this.S;
      if (!S.account) {
        S.account = { createdAt: clock(), onboardedAt: null, saved: { category: [], subcategory: [], level: [], locations: [] } };
        this.req('GET /api/users', 'no row: INSERT users (onboarding_completed_at = NULL)');
      } else {
        this.req('GET /api/users', `row found: onboardingCompletedAt = ${S.account.onboardedAt ? '"' + S.account.onboardedAt + '"' : 'null'}`);
      }
      return S.account;
    }
    postOnboarding(skipped) {
      const S = this.S; const d = S.draft;
      const body = {
        category: [...d.cats],
        subcategory: d.cats.has(SWE) ? [...d.subs] : [],
        level: [...d.levels],
        locations: [...d.locs],
        skipped,
      };
      S.account.saved = { category: body.category, subcategory: body.subcategory, level: body.level, locations: body.locations };
      if (!S.account.onboardedAt) S.account.onboardedAt = clock();
      const n = body.category.length + body.subcategory.length + body.level.length + body.locations.length;
      this.req(`POST /api/users/onboarding {${n} answers, skipped: ${skipped}}`, `UPSERT user_saved_filters; SET onboarding_completed_at = now()`);
    }

    /* ── flow ── */
    signIn() {
      const S = this.S;
      S.runNo += 1;
      S.run = { no: S.runNo, device: S.device, kind: S.account ? 'Returning' : 'New', taps: 0, t0: performance.now() };
      S.screen = 'wait'; this.render();
      setTimeout(() => {
        const u = this.getUser();
        if (u.onboardedAt) {
          this.req('<OnboardingGate/>', 'onboardingCompletedAt is set: render nothing. /jobs shows.');
          S.screen = 'jobs'; S.justDone = false;
          this.endRun('Went to the list');
        } else {
          this.req('<OnboardingGate/>', 'onboardingCompletedAt === null: open the questions full screen');
          // fromStep -1: the bar fills from empty to one third as the questions open.
          S.screen = 'onboard'; S.enter = true; S.step = 0; S.fromStep = -1; S.draft = emptyDraft();
        }
        this.render({ focusTitle: true, top: true });
      }, reduced() ? 150 : 650);
    }
    finish(skipped) {
      const S = this.S;
      this.postOnboarding(skipped);
      const a = S.account.saved; const any = a.category.length + a.level.length + a.locations.length > 0;
      S.screen = 'jobs'; S.justDone = any; S.snackEnter = any; S.q = '';
      this.snackTimer(any ? 6000 : 0);
      S.announce = any ? 'Saved as your filters.' : 'Skipped. The questions will not come back.';
      this.endRun(skipped ? 'Skipped' : 'Finished');
      this.render({ focusTitle: true, top: true });
    }
    endRun(result) {
      const S = this.S; if (!S.run) return;
      const secs = Math.max(1, Math.round((performance.now() - S.run.t0) / 1000));
      S.runs.unshift({ ...S.run, result, secs });
      S.run = null;
    }
    signOut() {
      const S = this.S;
      if (!S.account) return;
      this.req('sign out', 'session cleared; the users row stays');
      this.snackTimer(0);
      Object.assign(S, { screen: 'signin', menu: false, justDone: false, run: null, q: '' });
      this.render({ top: true });
    }
    reset() {
      const S = this.S;
      if (S.account) this.req('reset demo', 'DELETE users row (next sign-in is a new account)');
      this.snackTimer(0);
      Object.assign(S, { account: null, screen: 'signin', menu: false, justDone: false, run: null, draft: emptyDraft(), q: '' });
      this.render({ top: true });
    }

    /* ── events ── */
    onClick(e) {
      const S = this.S;
      const inScreen = e.target.closest('.screen');
      if (inScreen && S.run && e.target.closest('input, button')) S.run.taps += 1;
      const el = e.target.closest('[data-act]'); if (!el) { if (S.menu && inScreen) { S.menu = false; this.render(); } return; }
      const a = el.dataset.act;
      if (a === 'signin') return this.signIn();
      if (a === 'skip') return this.finish(true);
      if (a === 'done') return this.finish(false);
      if (a === 'next') { S.fromStep = S.step; S.step = Math.min(STEPS - 1, S.step + 1); S.q = ''; return this.render({ focusTitle: true, top: true }); }
      if (a === 'back') { S.fromStep = S.step; S.step = Math.max(0, S.step - 1); S.q = ''; return this.render({ focusTitle: true, top: true }); }
      if (a === 'loc-pick') { S.draft.locs.add(el.dataset.v); S.q = ''; S.announce = `${locShort(el.dataset.v)} added.`; return this.render({ focusId: 'loc-q' }); }
      if (a === 'avatar') { S.menu = !S.menu; return this.render({ focusId: S.menu ? 'm-out' : 'avatar' }); }
      if (a === 'signout' || a === 'side-signout') return this.signOut();
      if (a === 'reset') return this.reset();
      if (a === 'note-x') { S.justDone = false; this.snackTimer(0); return this.render({ focusTitle: true }); }
      if (a === 'toast') { S.toast = el.dataset.msg; this.render(); clearTimeout(this._tt); this._tt = setTimeout(() => { S.toast = ''; this.render(); }, 2200); }
    }
    onChange(e) {
      const S = this.S; const t = e.target;
      if (t.name === 'device') { S.device = t.value; S.menu = false; return this.render({ focusId: `dev-${t.value}` }); }
      const q = t.dataset.q; if (!q) return;
      const set = { cat: S.draft.cats, sub: S.draft.subs, lvl: S.draft.levels, loc: S.draft.locs }[q];
      if (t.checked) set.add(t.value); else set.delete(t.value);
      if (q === 'cat' && t.value === SWE && !t.checked) S.draft.subs.clear();
      if (q === 'cat' && t.value === SWE) S.announce = t.checked ? `${SUBS.length} specialties shown under Software Engineering.` : 'Specialties hidden.';
      this.render({ focusId: t.id, anim: q === 'cat' && t.value === SWE && t.checked });
    }
    onInput(e) { if (e.target.id === 'loc-q') { this.S.q = e.target.value; this.render({ focusId: 'loc-q', caret: e.target.selectionStart }); } }
    onKey(e) {
      const S = this.S;
      // Escape closes the questions, and it counts as Skip (plan claim 1.4).
      if (e.key === 'Escape' && S.screen === 'onboard') { e.preventDefault(); return this.finish(true); }
      if (e.key === 'Escape' && S.menu) { S.menu = false; this.render({ focusId: 'avatar' }); }
      if (e.key === 'Enter' && e.target.id === 'loc-q') {
        e.preventDefault(); const first = this.suggestions()[0];
        if (first) { S.draft.locs.add(first); S.q = ''; S.announce = `${locShort(first)} added.`; this.render({ focusId: 'loc-q' }); }
      }
    }

    /* ── data ── */
    matches(f) {
      const subs = new Set(f.subcategory.flatMap((s) => SUB_EXPAND[s] || [s]));
      const lv = new Set(f.level.flatMap((s) => LEVEL_EXPAND[s] || [s]));
      return JOBS.filter((j) =>
        (!f.category.length || f.category.includes(j.cat)) &&
        (j.cat !== SWE || !subs.size || subs.has(j.sub)) &&
        (!lv.size || lv.has(j.level)) &&
        (!f.locations.length || f.locations.some((l) => l === j.loc || (l === US && /, US$/.test(j.loc)))));
    }
    suggestions() {
      const q = this.S.q.trim().toLowerCase(); if (!q) return [];
      return LOC_ALL.filter((l) => l.toLowerCase().includes(q) && !this.S.draft.locs.has(l)).slice(0, 5);
    }

    /* ── the questions ── */
    roleQ() {
      const d = this.S.draft; const open = d.cats.has(SWE);
      const rows = CATS.map((c) => {
        const isSwe = c.slug === SWE; const on = d.cats.has(c.slug);
        const extra = isSwe ? `${open ? ' aria-controls="swe-subs"' : ''} aria-describedby="swe-desc"` : '';
        // Only a chevron: it turns when the row opens. Screen readers still hear the count in the label.
        const meta = isSwe ? `<span class="meta" aria-hidden="true">${I.chev}</span>` : '';
        let html = `<label class="row${isSwe && open ? ' open' : ''}"><input type="checkbox" id="cat-${c.slug}" data-q="cat" value="${c.slug}"${on ? ' checked' : ''}${extra}><span class="box">${I.check}</span><span class="lbl">${c.label}${isSwe ? `<span class="sr">, ${SUBS.length} specialties</span>` : ''}</span>${meta}</label>`;
        if (isSwe) {
          html += `<span id="swe-desc" class="sr">Checking it shows the specialties right below it.</span>`;
          if (open) {
            html += `<div class="reveal" id="swe-subs"><fieldset><legend class="sub"><span class="sr">Software Engineering specialties. </span>Select for more specific roles</legend><div class="chips">${
              SUBS.map((s) => this.chip('sub', s.slug, s.label, d.subs.has(s.slug))).join('')}</div></fieldset></div>`;
          }
        }
        return html;
      }).join('');
      return `<div class="rows">${rows}</div>`;
    }
    chip(q, v, text, on) {
      return `<label class="chip"><input type="checkbox" id="${q}-${v.replace(/\W+/g, '_')}" data-q="${q}" value="${esc(v)}"${on ? ' checked' : ''}>${I.check}<span>${esc(text)}</span></label>`;
    }
    levelQ() {
      const d = this.S.draft;
      return `<div class="chips">${LEVELS.map((l) => this.chip('lvl', l.slug, l.label, d.levels.has(l.slug))).join('')}</div>`;
    }
    locQ() {
      const d = this.S.draft; const S = this.S;
      const extra = [...d.locs].filter((l) => !LOC_PRESETS.includes(l));
      const chips = LOC_PRESETS.concat(extra).map((l) => this.chip('loc', l, locShort(l), d.locs.has(l))).join('');
      const sugs = this.suggestions();
      const list = S.q.trim()
        ? `<ul class="sugs" id="loc-list" aria-label="Matching places">${sugs.length ? sugs.map((l) => `<li><button type="button" data-act="loc-pick" data-v="${esc(l)}">${esc(locShort(l))}</button></li>`).join('') : '<li class="none">No match. Try a city name.</li>'}</ul>`
        : '';
      return `<div class="chips">${chips}</div>
        <div class="search"><label class="sr" for="loc-q">Search for another place</label>
        <div class="field">${I.search}<input id="loc-q" type="text" autocomplete="off" placeholder="City, state or country" value="${esc(S.q)}" aria-describedby="loc-help"${S.q.trim() ? ' aria-controls="loc-list"' : ''}></div>
        <span id="loc-help" class="sr">Type to see matches. Press Enter to add the first match.</span>${list}</div>`;
    }
    question(i, tag, cls, isTitle, id) {
      const Q = this.QUESTIONS()[i];
      return `<fieldset class="qset"><legend><${tag} class="${cls}"${id ? ` id="${id}"` : ''}${isTitle ? ' tabindex="-1" data-title' : ''}>${Q.h}</${tag}></legend>${Q.body()}</fieldset>`;
    }
    // "1/3" and a bar. A screen reader hears "Question 1 of 3"; the bar is decoration.
    // The fill slides from the last step's width to this one's (fromStep), once.
    progress(n) {
      const pct = (k) => `${(((k + 1) / STEPS) * 100).toFixed(2)}%`;
      const from = this.S.fromStep == null ? n : this.S.fromStep;
      return {
        count: `<span class="prog-n" aria-hidden="true">${n + 1}/${STEPS}</span><span class="sr">Question ${n + 1} of ${STEPS}</span>`,
        bar: `<span class="prog-track" aria-hidden="true"><span class="prog-fill" style="--from:${pct(from)};--to:${pct(n)}"></span></span>`,
      };
    }
    QUESTIONS() {
      return [
        { h: 'What roles are you looking for?', body: () => this.roleQ() },
        { h: 'Which levels fit you?', body: () => this.levelQ() },
        { h: 'Where do you want to work?', body: () => this.locQ() },
      ];
    }
    // The step row: 1/3 and Skip, then the bar.
    stepRow() {
      const S = this.S;
      const p = this.progress(S.step);
      return `<div class="qnav"><div class="col"><div class="qline">${p.count}<span class="grow"></span>`
        + `<button type="button" class="navbtn skip" data-act="skip">Skip</button></div>${p.bar}</div></div>`;
    }
    // Back and Continue. Back is disabled on question 1: there is nothing to go back to.
    next() {
      const S = this.S; const last = S.step === STEPS - 1;
      return `<button type="button" class="btn back" data-act="back"${S.step ? '' : ' disabled'}>Back</button>`
        + `<button type="button" class="btn pri" data-act="${last ? 'done' : 'next'}">${last ? 'Show my jobs' : 'Continue'}</button>`;
    }

    /* ── the production page ── */
    bar(right) {
      return `<div class="bar"><span class="mark" aria-label="onesecondswe">onesecondswe<span class="dot"></span></span><span class="grow"></span>${right || ''}</div>`;
    }
    appBar(signedIn) {
      const S = this.S;
      return `<header class="appbar"><button type="button" class="tog" aria-label="Toggle sidebar"${toast('In the app this opens or closes the side menu.')}>${I.side}</button>`
        + `<span class="wm" aria-label="onesecondswe"><span class="full" aria-hidden="true">onesecondswe</span><span class="one" aria-hidden="true">1s<span class="dot"></span></span></span><span class="grow"></span>`
        + (signedIn ? `<button type="button" class="av-btn" id="avatar" data-act="avatar" aria-haspopup="menu" aria-expanded="${S.menu}" aria-label="Account menu"><span class="av">B</span></button>` : '')
        + `</header>`
        + (S.menu && signedIn ? `<div class="menu" role="menu"><button role="menuitem"${toast('In the app this opens Saved Filters.')}>Saved Filters</button><button role="menuitem" id="m-out" data-act="signout">Sign out</button></div>` : '');
    }
    drawer() {
      const it = (t, ic, on) => `<button type="button" class="it${on ? ' on' : ''}"${on ? ' aria-current="page"' : toast(`In the app this opens ${t}.`)}>${I[ic]}<span>${t}</span></button>`;
      return `<nav class="drawer" aria-label="App navigation"><div class="sh">JOBS FROM THE SOURCE</div>`
        + it('Recent Job Postings', 'schedule', true) + it('Company Hiring Trends', 'trend') + it('Saved Filters', 'filter') + it('Add Companies', 'addbiz')
        + `<hr><div class="sh">INFO</div>` + it('Curated Companies', 'biz') + it('Give Feedback', 'thumb') + it('Why This Was Built', 'info')
        + `<span class="grow"></span><hr>` + it('Account', 'acct') + `</nav>`;
    }
    // RecentJobsFilters: the closed fields show the filter values, so they show the answers too.
    filters(f) {
      const catTxt = f.category.length || f.subcategory.length ? [...f.category, ...f.subcategory].map((s) => label(CATS.concat(SUBS), s)).join(', ') : 'All';
      const lvlTxt = f.level.length ? f.level.map((s) => label(LEVELS, s)).join(', ') : 'All';
      const sel = (lab, val, w) => `<button type="button" class="fld up ${w}"${toast(`In the app this opens the ${lab} menu.`)}><span class="flab">${lab}</span><span class="fval">${esc(val)}</span>${I.drop}</button>`;
      const loc = f.locations.length
        ? `<button type="button" class="fld up w240"${toast('In the app this searches places.')}><span class="flab">Location</span>${f.locations.map((l) => `<span class="tag">${esc(l)}${I.cancel}</span>`).join('')}<span class="ph">Search location...</span>${I.drop}</button>`
        : `<button type="button" class="fld w240"${toast('In the app this searches places.')}><span class="flab">Location</span>${I.drop}</button>`;
      return `<div class="flt"><button type="button" class="fld kw"${toast('In the app this adds a keyword.')}><span class="flab">Keywords</span>${I.drop}</button>`
        + `<div class="frow">${sel('Time Window', 'All time', 'w150')}${sel('Job Category', catTxt, 'w170')}${sel('Level', lvlTxt, 'w170')}${loc}</div>`
        + `<div><button type="button" class="rst"${toast('In the app this clears every filter.')}>Reset Filters</button></div></div>`;
    }
    // JobListingCard
    card(j) {
      const src = (window.PROTO_LOGOS || {})[j.id];
      const tile = src ? `<img src="${src}" alt="">` : esc(j.co[0]);
      const enr = (j.cat === SWE && j.sub ? [label(SUBS, j.sub)] : [label(CATS, j.cat)]).concat(label(LEVELS, j.level));
      const open = `In the app this opens the posting on the ${j.co} site.`;
      return `<article class="jc"${toast(open)}><div class="jc-c">`
        + `<div class="jc-h"><div class="jc-hl"><span class="logo" aria-hidden="true">${tile}</span><div class="jc-tx"><div class="jc-co">${esc(j.co)}</div><h3 class="jc-t">${esc(j.title)}</h3></div></div>`
        + `<button type="button" class="jc-ap"${toast(open)}>Apply</button></div>`
        + `<div class="crow"><span class="mc o">${esc(j.loc)}</span></div>`
        + `<div class="crow">${enr.map((c) => `<span class="mc f">${esc(c)}</span>`).join('')}</div>`
        + `<button type="button" class="dm"${toast(`In the app this opens the ${j.co} hiring team on LinkedIn.`)}>DM the hiring team${I.ext}</button>`
        + `<span class="posted">Posted ${postedAgo(j.ago)}</span></div></article>`;
    }
    pageContent(f, o) {
      const S = this.S; const list = this.matches(f);
      const cards = list.length
        ? list.map((j) => this.card(j)).join('') + `<p class="pg-end">All ${list.length} jobs loaded</p>`
        : `<div class="pg-empty"><b>No jobs found matching your filters</b><span>Try adjusting your filters or extending the time window</span></div>`;
      return `<h1 class="pg-h1" tabindex="-1"${o.inert ? '' : ' data-title'}>Recent Job Postings</h1>`
        + `${this.filters(f)}<div class="jl">${cards}</div>`;
    }
    page(f, o = {}) {
      const S = this.S;
      const main = `<main class="body pg-main" id="jobs-body">${this.pageContent(f, o)}</main>`;
      return `<div class="pg"${o.inert ? ' inert' : ''}>${this.appBar(true)}${this.desk ? `<div class="pg-row">${this.drawer()}${main}</div>` : main}</div>`
        + (S.justDone && !o.inert ? this.snack() : '');
    }
    // The "Saved filters" toast. The live region (S.announce) speaks it, so it has no role of its own.
    snack() {
      const S = this.S;
      return `<div class="snack${S.snackEnter ? ' enter' : ''}" id="snack"><span class="ok" aria-hidden="true">${I.check}</span>`
        + `<button type="button" class="go"${toast('In the app this opens Saved Filters (/saved-filters).')}>Saved filters</button>`
        + `<button type="button" class="x" data-act="note-x" aria-label="Dismiss">×</button></div>`;
    }
    snackTimer(ms) {
      clearTimeout(this._st);
      if (ms) this._st = setTimeout(() => { this.S.justDone = false; this.render(); }, ms);
    }

    /* ── screens ── */
    screenSignin() {
      const known = !!this.S.account;
      const inner = `<h1 tabindex="-1" data-title>Sign in</h1>
        <p>${known ? 'Welcome back.' : 'Save your filters and see new jobs first.'}</p>
        <button class="btn wide" data-act="signin">${I.g}Continue with Google</button>
        <button class="btn wide" data-act="signin">Continue with email</button>
        <p class="small">${known ? 'This account exists. It is onboarded, so the questions will not show.' : 'No account yet. The first sign-in creates it.'}</p>`;
      if (this.desk) return `<div class="pg">${this.appBar(false)}<div class="body si-desk"><div class="signin">${inner}</div></div></div>`;
      return `<div class="signin"><span class="bigmark">onesecondswe<span class="mark"><span class="dot"></span></span></span>${inner}</div>`;
    }
    screenWait() {
      const w = '<div class="wait" role="status">Signing in…</div>';
      return this.desk ? `<div class="pg">${this.appBar(false)}${w}</div>` : w;
    }
    // A full-screen dialog at every size, so nothing shows behind the questions.
    screenQuestions() {
      const S = this.S;
      return this.bar() + this.stepRow()
        + `<div class="body qbody" id="qbody"><div class="col">${this.question(S.step, 'h1', 'q', true)}</div></div>`
        + `<div class="foot qfoot" id="qfoot"><div class="col">${this.next()}</div></div>`;
    }

    sidePanel() {
      const S = this.S; const a = S.account;
      const dev = [['phone', 'Phone', 'Under 600 px wide'], ['desktop', 'Desktop', '1280 × 800 window']]
        .map(([k, t, s]) => `<label><input type="radio" id="dev-${k}" name="device" value="${k}"${S.device === k ? ' checked' : ''}><b>${s}</b><span>${t}</span></label>`).join('');
      const state = !a ? 'No account yet. The next sign-in creates one.'
        : a.onboardedAt ? `<span class="ok">Onboarded at ${a.onboardedAt}.</span> A new sign-in goes straight to the list.`
        : `<span class="wait">Account created at ${a.createdAt}. Not onboarded yet.</span>`;
      const v = (x) => (x == null ? '<span class="null">null</span>' : `<span class="set">"${x}"</span>`);
      const arr = (xs) => (xs.length ? `[${xs.map((x) => `"${esc(x)}"`).join(', ')}]` : '[]');
      const db = !a ? '<span class="k">-- users: no row for this person</span>'
        : `<span class="k">users.</span>onboarding_completed_at = ${v(a.onboardedAt)}\n<span class="k">user_saved_filters.</span>category    = ${arr(a.saved.category)}\n<span class="k">user_saved_filters.</span>subcategory = ${arr(a.saved.subcategory)}\n<span class="k">user_saved_filters.</span>level       = ${arr(a.saved.level)}\n<span class="k">user_saved_filters.</span>locations   = ${arr(a.saved.locations)}`;
      const log = S.log.length ? S.log.map((l) => `<li><span class="t">${l.t}</span> ${esc(l.line)}<span class="r">${esc(l.result)}</span></li>`).join('') : '<li class="t">Nothing yet. Press Continue with Google in the prototype.</li>';
      const runs = S.runs.length
        ? `<table class="runs"><thead><tr><th>Run</th><th>Screen</th><th>Account</th><th>Result</th><th>Taps</th><th>Time</th></tr></thead><tbody>${S.runs.map((r) => `<tr><td class="n">${r.no}</td><td>${r.device === 'desktop' ? 'Desktop' : 'Phone'}</td><td>${r.kind}</td><td>${r.result}</td><td class="n">${r.kind === 'Returning' ? '0' : r.taps}</td><td class="n">${r.secs} s</td></tr>`).join('')}</tbody></table>`
        : '<p class="empty-runs">Each sign-in adds a row here, so you can compare runs.</p>';
      const ctl = `<div class="side ctl"><div class="grp">
          <div class="dev"><h3>Screen</h3><div class="vers two" role="radiogroup" aria-label="Screen size">${dev}</div></div>
          <h3>Version A · One question on each screen</h3><p>${ABOUT}</p>
          <p class="state" aria-live="polite">${state}</p>
          <div class="acts"><button class="sbtn" data-act="side-signout"${a && S.screen !== 'signin' ? '' : ' disabled'}>Sign out, then sign in again</button><button class="sbtn" data-act="reset">Start over as a new user</button></div></div></div>`;
      return ctl + `<div class="side">
        <div class="grp"><h3>Database</h3><pre class="db">${db}</pre></div>
        <div class="grp"><h3>Requests</h3><ol class="log">${log}</ol></div>
        <div class="grp"><h3>Runs</h3>${runs}</div>
      </div>`;
    }

    // Scale the 1280 x 800 desktop window to the width it has.
    fit() {
      const vp = this._root && this._root.querySelector('.desk-vp'); if (!vp) return;
      vp.style.setProperty('--s', Math.min(1, vp.clientWidth / DESK_W).toFixed(4));
    }

    render(o = {}) {
      const S = this.S; const R = this._root;
      const prev = R.querySelector('.screen .sb') || R.querySelector('.screen .body');
      const keepTop = prev ? prev.scrollTop : 0;
      let screen;
      if (S.screen === 'signin') screen = this.screenSignin();
      else if (S.screen === 'wait') screen = this.screenWait();
      else if (S.screen === 'onboard') screen = this.screenQuestions();
      else screen = this.page(S.account.saved);
      const t = S.toast ? `<div class="toast" role="status">${esc(S.toast)}</div>` : '';
      const anim = (o.anim || S.enter) && !reduced() ? ' anim' : '';
      const inner = `<div class="screen${this.desk ? ' desk' : ''}${anim}" aria-label="Prototype ${this.desk ? 'desktop' : 'phone'} screen">${screen}${t}<div class="sr" aria-live="polite">${esc(S.announce)}</div></div>`;
      const device = this.desk
        ? `<div class="deskframe"><div class="dbar" aria-hidden="true"><i></i><i></i><i></i><span class="url">onesecondswe.dev/jobs</span></div><div class="desk-vp">${inner}</div></div>`
        : `<div class="phone">${inner}</div>`;
      R.innerHTML = `<style>${CSS}</style><div class="wrap${this.desk ? ' desk' : ''}">${device}${this.sidePanel()}</div>`;
      S.enter = false; S.fromStep = null; S.announce = ''; S.snackEnter = false;
      this.fit();
      const nb = R.querySelector('.screen .sb') || R.querySelector('.screen .body');
      if (nb && !o.top) nb.scrollTop = keepTop;
      const sn = R.getElementById('snack');
      if (sn) {
        const hold = () => this.snackTimer(0);
        const resume = () => { if (!sn.matches(':hover') && !sn.contains(R.activeElement)) this.snackTimer(3000); };
        sn.addEventListener('mouseenter', hold); sn.addEventListener('focusin', hold);
        sn.addEventListener('mouseleave', resume); sn.addEventListener('focusout', () => setTimeout(resume, 0));
      }
      const qb = R.getElementById('qbody'); const qf = R.getElementById('qfoot');
      if (qb && qf) {
        const edge = () => qf.classList.toggle('edge', qb.scrollTop + qb.clientHeight < qb.scrollHeight - 1);
        qb.addEventListener('scroll', edge, { passive: true }); edge();
      }
      if (o.focusId) {
        const el = R.getElementById(o.focusId);
        if (el) { el.focus({ preventScroll: true }); if (o.caret != null && el.setSelectionRange) el.setSelectionRange(o.caret, o.caret); }
      } else if (o.focusTitle && !o.first) {
        const ti = R.querySelector('[data-title]'); if (ti) ti.focus({ preventScroll: true });
      }
    }
  }
  customElements.define('proto-lab', ProtoLab);
})();
