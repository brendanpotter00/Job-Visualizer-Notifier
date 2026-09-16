import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { GravityPrototype } from '../../../pages/LandingPage/prototypes/GravityPrototype/GravityPrototype';
import { detectWebGLSupport } from '../../../pages/LandingPage/prototypes/shared3d/detectWebGL';
import {
  CONSTRAINED_BODY_COUNT,
  DESKTOP_BODY_COUNT,
} from '../../../pages/LandingPage/prototypes/shared3d/experienceTier';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { selectTriptychSlots } from '../../../pages/LandingPage/sections/triptychJobs';
import { buildMockJobs } from '../../../pages/LandingPage/mockData';

// Mock boundary = the scene module: <Canvas> throws in jsdom, and mocking here
// keeps three/rapier entirely out of the test process (mirroring the runtime
// invariant that only the lazy scene chunk ever loads them).
vi.mock(
  '../../../pages/LandingPage/prototypes/GravityPrototype/GravityScene',
  () => ({
    default: (props: { roster: readonly { companyId: string }[]; maxDpr: number }) => (
      <div
        data-testid="gravity-scene"
        data-roster-size={props.roster.length}
        data-max-dpr={props.maxDpr}
      />
    ),
  })
);

// jsdom has no WebGL: default every test to the fallback tier, opt in per test.
vi.mock('../../../pages/LandingPage/prototypes/shared3d/detectWebGL', () => ({
  detectWebGLSupport: vi.fn(() => false),
}));

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
const PILE_LABEL = 'Companies tracked by onesecondswe';

function renderGravity() {
  return renderWithProviders(
    <GravityPrototype
      content={LANDING_CONTENT}
      jobs={buildMockJobs(NOW)}
      sparse={false}
      now={NOW}
    />,
    { initialEntries: ['/landing'] }
  );
}

/** Pin the capability hints jsdom would otherwise take from the host machine. */
function stubCores(cores: number) {
  Object.defineProperty(window.navigator, 'hardwareConcurrency', {
    value: cores,
    configurable: true,
  });
}

function stubMatchMedia(reduceMotion: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: reduceMotion && query === '(prefers-reduced-motion: reduce)',
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

/** CTA buttons only — the footer carries plain text links with the same labels. */
function buttonLinks(name: string) {
  return screen
    .getAllByRole('link', { name })
    .filter((el) => el.classList.contains('MuiButton-root'));
}

afterEach(() => {
  Reflect.deleteProperty(window.navigator, 'hardwareConcurrency');
  Reflect.deleteProperty(window, 'matchMedia');
});

describe('GravityPrototype', () => {
  // The bar lives OUTSIDE the clipped hero wrapper (a sticky child of an
  // `overflow: hidden` box scrolls away with it), so assert it precedes the h1.
  it('opens with the shared landing header above the clipped hero', () => {
    renderGravity();
    const bar = screen.getByTestId('landing-header');
    expect(
      within(bar).getByRole('link', { name: LANDING_CONTENT.header.wordmark.label })
    ).toHaveAttribute('href', LANDING_CONTENT.header.wordmark.to);
    expect(
      within(bar).getByRole('link', { name: LANDING_CONTENT.header.signUp.label })
    ).toHaveClass('MuiButton-contained');
    expect(
      bar.compareDocumentPosition(screen.getByRole('heading', { level: 1 })) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  // One h1 in two tones: the hook and the continuation are both inside it, so
  // the page's single heading carries the query phrase as well as the line.
  it('renders the two-tone hero as the single h1', () => {
    renderGravity();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent(LANDING_CONTENT.hero.headline);
    expect(h1).toHaveTextContent(LANDING_CONTENT.hero.continuation);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });

  // The same pair, hero and closer: a filled "Browse jobs" and a quiet text
  // "Create free account". Two of each, and never an outlined variant.
  it('carries the CTA pair in the hero and again in the closing block', () => {
    renderGravity();
    const primaries = buttonLinks(LANDING_CONTENT.ctas.primary.label);
    const secondaries = buttonLinks(LANDING_CONTENT.ctas.secondary.label);
    expect(primaries).toHaveLength(2);
    expect(secondaries).toHaveLength(2);
    for (const button of primaries) {
      expect(button).toHaveClass('MuiButton-contained');
      expect(button).toHaveAttribute('href', LANDING_CONTENT.ctas.primary.to);
    }
    for (const button of secondaries) {
      expect(button).toHaveClass('MuiButton-text');
      expect(button).toHaveAttribute('href', LANDING_CONTENT.ctas.secondary.to);
    }
    const closer = screen.getByTestId('closing-cta');
    expect(within(closer).getByRole('heading', { level: 2 })).toHaveTextContent(
      LANDING_CONTENT.closing.heading
    );
  });

  // The mock posting-cadence line behind the hero copy was removed
  // (owner-directed 2026-09-10): the pile is the hero's only picture.
  it('draws nothing decorative behind the hero copy', () => {
    renderGravity();
    expect(screen.queryByTestId('hero-trendline')).not.toBeInTheDocument();
    expect(document.querySelector('section svg path[stroke-opacity]')).toBeNull();
  });

  it('fallback tier (no WebGL): pre-settled DOM logo grid, scene never mounts', () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(false);
    renderGravity();
    const grid = screen.getByLabelText(PILE_LABEL);
    expect(within(grid).getAllByRole('img')).toHaveLength(CONSTRAINED_BODY_COUNT);
    expect(screen.queryByTestId('gravity-scene')).not.toBeInTheDocument();
  });

  it('full desktop tier: lazy-mounts the scene with the desktop roster and full dpr', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(12);
    renderGravity();
    const scene = await screen.findByTestId('gravity-scene');
    expect(scene).toHaveAttribute('data-roster-size', String(DESKTOP_BODY_COUNT));
    expect(scene).toHaveAttribute('data-max-dpr', '2');
    // The settled pile IS the logo wall — no DOM grid/marquee duplicate below.
    expect(screen.queryByLabelText(PILE_LABEL)).not.toBeInTheDocument();
  });

  it('constrained hardware keeps the full tier but shrinks the roster and the dpr cap', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(4);
    renderGravity();
    const scene = await screen.findByTestId('gravity-scene');
    expect(scene).toHaveAttribute('data-roster-size', String(CONSTRAINED_BODY_COUNT));
    expect(scene).toHaveAttribute('data-max-dpr', '1.5');
  });

  it('prefers-reduced-motion forces the DOM fallback even with WebGL available', () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(12);
    stubMatchMedia(true);
    renderGravity();
    expect(screen.getByLabelText(PILE_LABEL)).toBeInTheDocument();
    expect(screen.queryByTestId('gravity-scene')).not.toBeInTheDocument();
  });

  it('carries the three-slot fresh-jobs triptych under its own heading', () => {
    renderGravity();
    const [earlyCareer, last24h, bigTech] = selectTriptychSlots(buildMockJobs(NOW), NOW);
    const triptych = screen.getByTestId('fresh-jobs-triptych');
    expect(within(triptych).getByRole('heading', { level: 2 })).toHaveTextContent(
      LANDING_CONTENT.freshJobs.heading
    );
    for (const slot of [earlyCareer, last24h, bigTech]) {
      const region = screen.getByTestId(`triptych-slot-${slot.id}`);
      // By ROLE, not by text: each slot also carries hidden height sizers for
      // the rest of its pool, and those are aria-hidden — so a role query sees
      // only the job actually on screen. See FlippingCard's SizerStack.
      expect(within(region).getByRole('heading', { name: slot.jobs[0].title })).toBeInTheDocument();
    }
  });

  it('renders every section from the content config', () => {
    renderGravity();
    for (const row of LANDING_CONTENT.comparison.rows) {
      const region = screen.getByTestId(`comparison-row-${row.id}`);
      expect(within(region).getByText(row.linkedin)).toBeInTheDocument();
      expect(within(region).getByText(row.onesecondswe)).toBeInTheDocument();
    }
    for (const step of LANDING_CONTENT.howItWorks.steps) {
      expect(screen.getByText(step.line)).toBeInTheDocument();
    }
    expect(screen.getByText(LANDING_CONTENT.howItWorks.closer.line)).toBeInTheDocument();
    for (const stat of LANDING_CONTENT.proof.stats) {
      expect(screen.getByText(stat.sentence)).toBeInTheDocument();
    }
    for (const feature of LANDING_CONTENT.featureMatrix.features) {
      expect(screen.getByText(feature.detail)).toBeInTheDocument();
    }
    expect(
      screen.getByRole('link', { name: LANDING_CONTENT.featureMatrix.nextUp.label })
    ).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.faq.entries[0].question)).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.categoryLine)).toBeInTheDocument();
  });

  // Order is the section contract: live proof, then the comparison the owner
  // asked for, then the mechanism, the numbers, the companies, the matrix, the
  // FAQ, and the closing line before the footer. Assert the whole sequence
  // rather than mere presence.
  it('orders the sections: triptych → LinkedIn → how-it-works → numbers → companies → matrix → FAQ → closer → footer', () => {
    renderGravity();
    const markers = [
      screen.getByTestId('fresh-jobs-triptych'),
      screen.getByTestId('linkedin-comparison'),
      screen.getByTestId('how-it-works'),
      screen.getByTestId('proof-stats'),
      screen.getByRole('heading', { name: LANDING_CONTENT.companies.heading, level: 2 }),
      screen.getByTestId('feature-matrix'),
      screen.getByRole('heading', { name: LANDING_CONTENT.faq.heading, level: 2 }),
      screen.getByTestId('closing-cta'),
      screen.getByText(LANDING_CONTENT.categoryLine),
    ];
    for (let i = 1; i < markers.length; i += 1) {
      expect(
        markers[i - 1].compareDocumentPosition(markers[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
        `section ${i} is out of order`
      ).toBeTruthy();
    }
  });

  // Landmarks for crawlers and screen readers: one main, every section named
  // by its own heading, and the footer outside main.
  it('wraps the page in a main landmark of labelled sections', () => {
    renderGravity();
    const main = screen.getByRole('main');
    const sections = Array.from(main.querySelectorAll('section'));
    expect(sections.length).toBeGreaterThanOrEqual(9);
    for (const section of sections) {
      const labelledBy = section.getAttribute('aria-labelledby');
      expect(labelledBy, 'every section must point at its heading').toBeTruthy();
      expect(document.getElementById(labelledBy!), `missing heading #${labelledBy}`).not.toBeNull();
    }
    expect(main.contains(screen.getByRole('contentinfo'))).toBe(false);
  });
});
