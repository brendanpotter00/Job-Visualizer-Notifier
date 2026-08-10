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
  it('renders the source hero as the single h1 with the primary CTA', () => {
    renderGravity();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent(LANDING_CONTENT.heroVariants.source.headline);
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(
      screen.getAllByRole('link', { name: LANDING_CONTENT.ctas.primary.label }).length
    ).toBeGreaterThan(0);
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

  it('keeps the shared sections: activity stats, fresh-jobs ticker, FAQ, footer', () => {
    renderGravity();
    expect(screen.getByText(/tracked in the past 24 hours/)).toBeInTheDocument();
    expect(screen.getByText('Posted in the last 48 hours')).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.faq[0].question)).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.footer.tagline)).toBeInTheDocument();
  });
});
