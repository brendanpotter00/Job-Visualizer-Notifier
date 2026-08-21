import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { GravityPrototype } from '../../../pages/AdminLandingPrototypesPage/prototypes/GravityPrototype/GravityPrototype';
import { detectWebGLSupport } from '../../../pages/AdminLandingPrototypesPage/prototypes/shared3d/detectWebGL';
import {
  CONSTRAINED_BODY_COUNT,
  DESKTOP_BODY_COUNT,
} from '../../../pages/AdminLandingPrototypesPage/prototypes/shared3d/experienceTier';
import { LANDING_CONTENT } from '../../../pages/AdminLandingPrototypesPage/content';
import { selectTriptychSlots } from '../../../pages/AdminLandingPrototypesPage/sections/triptychJobs';
import { buildMockJobs, MOCK_STATS } from '../../../pages/AdminLandingPrototypesPage/mockData';

// Mock boundary = the scene module: <Canvas> throws in jsdom, and mocking here
// keeps three/rapier entirely out of the test process (mirroring the runtime
// invariant that only the lazy scene chunk ever loads them).
vi.mock(
  '../../../pages/AdminLandingPrototypesPage/prototypes/GravityPrototype/GravityScene',
  () => ({
    default: (props: {
      roster: readonly { companyId: string }[];
      maxDpr: number;
      showShadows: boolean;
    }) => (
      <div
        data-testid="gravity-scene"
        data-roster-size={props.roster.length}
        data-max-dpr={props.maxDpr}
        data-show-shadows={String(props.showShadows)}
      />
    ),
  })
);

// jsdom has no WebGL: default every test to the fallback tier, opt in per test.
vi.mock('../../../pages/AdminLandingPrototypesPage/prototypes/shared3d/detectWebGL', () => ({
  detectWebGLSupport: vi.fn(() => false),
}));

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
const PILE_LABEL = 'Companies tracked by onesecondswe';

function renderGravity() {
  return renderWithProviders(
    <GravityPrototype
      content={LANDING_CONTENT}
      jobs={buildMockJobs(NOW)}
      stats={MOCK_STATS}
      sparse={false}
      now={NOW}
    />,
    { initialEntries: ['/admin/landing-prototypes?proto=gravity'] }
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

  // Gravity is converging as the primary landing design, so it carries the
  // anti-noise headline ("No reposts. No stale listings. No noise.").
  it('renders the anti-noise hero as the single h1 with both CTAs', () => {
    renderGravity();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent(LANDING_CONTENT.heroVariants.antiNoise.headline);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(
      screen.getAllByRole('link', { name: LANDING_CONTENT.ctas.primary.label }).length
    ).toBeGreaterThan(0);
    // The footer carries a plain text link with the same label; filter to buttons.
    const secondaries = screen
      .getAllByRole('link', { name: LANDING_CONTENT.ctas.secondary.label })
      .filter((el) => el.classList.contains('MuiButton-root'));
    expect(secondaries).toHaveLength(1);
    expect(secondaries[0]).toHaveClass('MuiButton-outlined');
    expect(secondaries[0]).toHaveAttribute('href', LANDING_CONTENT.ctas.secondary.to);
  });

  it('fallback tier (no WebGL): pre-settled DOM logo grid, scene never mounts', () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(false);
    renderGravity();
    const grid = screen.getByLabelText(PILE_LABEL);
    expect(within(grid).getAllByRole('img')).toHaveLength(CONSTRAINED_BODY_COUNT);
    expect(screen.queryByTestId('gravity-scene')).not.toBeInTheDocument();
  });

  it('full desktop tier: lazy-mounts the scene with the desktop roster and shadows', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(12);
    renderGravity();
    const scene = await screen.findByTestId('gravity-scene');
    expect(scene).toHaveAttribute('data-roster-size', String(DESKTOP_BODY_COUNT));
    expect(scene).toHaveAttribute('data-max-dpr', '2');
    expect(scene).toHaveAttribute('data-show-shadows', 'true');
    // The settled pile IS the logo wall — no DOM grid/marquee duplicate below.
    expect(screen.queryByLabelText(PILE_LABEL)).not.toBeInTheDocument();
  });

  it('constrained hardware keeps the full tier but shrinks the roster and drops shadows', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(4);
    renderGravity();
    const scene = await screen.findByTestId('gravity-scene');
    expect(scene).toHaveAttribute('data-roster-size', String(CONSTRAINED_BODY_COUNT));
    expect(scene).toHaveAttribute('data-max-dpr', '1.5');
    expect(scene).toHaveAttribute('data-show-shadows', 'false');
  });

  it('prefers-reduced-motion forces the DOM fallback even with WebGL available', () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(12);
    stubMatchMedia(true);
    renderGravity();
    expect(screen.getByLabelText(PILE_LABEL)).toBeInTheDocument();
    expect(screen.queryByTestId('gravity-scene')).not.toBeInTheDocument();
  });

  it('carries the three-slot fresh-jobs triptych where the single card used to be', () => {
    renderGravity();
    const [earlyCareer, last24h, bigTech] = selectTriptychSlots(buildMockJobs(NOW), NOW);
    expect(screen.getByTestId('fresh-jobs-triptych')).toBeInTheDocument();
    for (const slot of [earlyCareer, last24h, bigTech]) {
      const region = screen.getByTestId(`triptych-slot-${slot.id}`);
      // By ROLE, not by text: each slot also carries hidden height sizers for
      // the rest of its pool, and those are aria-hidden — so a role query sees
      // only the job actually on screen. See FlippingCard's SizerStack.
      expect(within(region).getByRole('heading', { name: slot.jobs[0].title })).toBeInTheDocument();
    }
    expect(screen.queryByTestId('rotating-job-card')).not.toBeInTheDocument();
    expect(screen.queryByText(/tracked in the past 24 hours/)).not.toBeInTheDocument();
  });

  it('keeps the shared sections below: FAQ and footer', () => {
    renderGravity();
    expect(screen.getByText(LANDING_CONTENT.faq[0].question)).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.footer.tagline)).toBeInTheDocument();
  });

  it('carries the two quiet text sections with their content copy', () => {
    renderGravity();
    for (const step of LANDING_CONTENT.howItWorks.steps) {
      expect(screen.getByText(step.line)).toBeInTheDocument();
    }
    expect(screen.getByText(LANDING_CONTENT.claims.apply_early_rolling.body)).toBeInTheDocument();
    for (const feature of LANDING_CONTENT.featureMatrix.features) {
      expect(screen.getByText(feature.detail)).toBeInTheDocument();
    }
    expect(
      screen.getByRole('link', { name: LANDING_CONTENT.featureMatrix.nextUp.label })
    ).toBeInTheDocument();
  });

  // The still text sections bracket the categories grid: one after the flipping
  // triptych, one before the FAQ. Order is the section contract, so assert the
  // whole below-hero sequence rather than mere presence.
  it('orders the below-hero sections triptych → how-it-works → categories → matrix → FAQ', () => {
    renderGravity();
    const markers = [
      screen.getByTestId('fresh-jobs-triptych'),
      screen.getByTestId('how-it-works'),
      screen.getByRole('heading', { name: 'Browse curated companies', level: 2 }),
      screen.getByTestId('feature-matrix'),
      screen.getByRole('heading', { name: 'Frequently asked questions', level: 2 }),
      screen.getByText(LANDING_CONTENT.footer.tagline),
    ];
    for (let i = 1; i < markers.length; i += 1) {
      expect(
        markers[i - 1].compareDocumentPosition(markers[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
        `section ${i} is out of order`
      ).toBeTruthy();
    }
  });
});
