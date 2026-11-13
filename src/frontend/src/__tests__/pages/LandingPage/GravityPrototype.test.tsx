import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { createTestStore, renderWithProviders } from '../../../test/testUtils';
import { GravityPrototype } from '../../../pages/LandingPage/prototypes/GravityPrototype/GravityPrototype';
import { detectWebGLSupport } from '../../../pages/LandingPage/prototypes/shared3d/detectWebGL';
import {
  CONSTRAINED_BODY_COUNT,
  DESKTOP_BODY_COUNT,
} from '../../../pages/LandingPage/prototypes/shared3d/experienceTier';
import { LANDING_CONTENT } from '../../../pages/LandingPage/content';
import { selectTriptychSlots } from '../../../pages/LandingPage/sections/triptychJobs';
import { buildRichLandingJobs, LANDING_NOW, seedLandingJobs } from './landingJobFixtures';

// Mock boundary = the scene module: <Canvas> throws in jsdom, and mocking here
// keeps three/rapier entirely out of the test process (mirroring the runtime
// invariant that only the lazy scene chunk ever loads them).
vi.mock(
  '../../../pages/LandingPage/prototypes/GravityPrototype/GravityScene',
  () => ({
    default: (props: {
      roster: readonly { companyId: string }[];
      maxDpr: number;
      compact: boolean;
    }) => (
      <div
        data-testid="gravity-scene"
        data-roster-size={props.roster.length}
        data-max-dpr={props.maxDpr}
        data-compact={String(props.compact)}
      />
    ),
  })
);

// jsdom has no WebGL: default every test to the fallback tier, opt in per test.
vi.mock('../../../pages/LandingPage/prototypes/shared3d/detectWebGL', () => ({
  detectWebGLSupport: vi.fn(() => false),
}));

const NOW = LANDING_NOW;
const PILE_LABEL = 'Companies tracked by onesecondswe';

async function renderGravity() {
  const store = createTestStore();
  await seedLandingJobs(store, buildRichLandingJobs(NOW), NOW);
  return renderWithProviders(<GravityPrototype content={LANDING_CONTENT} />, {
    store,
    initialEntries: ['/'],
  });
}

/** Pin the capability hints jsdom would otherwise take from the host machine. */
function stubCores(cores: number) {
  Object.defineProperty(window.navigator, 'hardwareConcurrency', {
    value: cores,
    configurable: true,
  });
}

function stubMatchMedia(reduceMotion: boolean, phone = false) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches:
        (reduceMotion && query === '(prefers-reduced-motion: reduce)') ||
        (phone && query.includes('max-width')),
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
  it('opens with the shared landing header above the clipped hero', async () => {
    await renderGravity();
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

  it('renders the hero as the single h1', async () => {
    await renderGravity();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent(LANDING_CONTENT.hero.headline);
    expect(h1.querySelector('span')).toBeNull();
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
  });

  it('carries the CTA pair in the hero and again in the closing block', async () => {
    await renderGravity();
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

  it('draws nothing decorative behind the hero copy', async () => {
    await renderGravity();
    expect(screen.queryByTestId('hero-trendline')).not.toBeInTheDocument();
    expect(document.querySelector('section svg path[stroke-opacity]')).toBeNull();
  });

  it('fallback tier (no WebGL): pre-settled DOM logo grid, scene never mounts', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(false);
    await renderGravity();
    const grid = screen.getByLabelText(PILE_LABEL);
    expect(within(grid).getAllByRole('img')).toHaveLength(CONSTRAINED_BODY_COUNT);
    expect(screen.queryByTestId('gravity-scene')).not.toBeInTheDocument();
  });

  it('full desktop tier: lazy-mounts the scene with the desktop roster and full dpr', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(12);
    await renderGravity();
    const scene = await screen.findByTestId('gravity-scene');
    expect(scene).toHaveAttribute('data-roster-size', String(DESKTOP_BODY_COUNT));
    expect(scene).toHaveAttribute('data-max-dpr', '2');
    expect(scene).toHaveAttribute('data-compact', 'false');
    // The settled pile IS the logo wall — no DOM grid/marquee duplicate below.
    expect(screen.queryByLabelText(PILE_LABEL)).not.toBeInTheDocument();
  });

  it('constrained hardware keeps the full tier but shrinks the roster and the dpr cap', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(4);
    await renderGravity();
    const scene = await screen.findByTestId('gravity-scene');
    expect(scene).toHaveAttribute('data-roster-size', String(CONSTRAINED_BODY_COUNT));
    expect(scene).toHaveAttribute('data-max-dpr', '1.5');
  });

  it('phone with WebGL: mounts the scene compact, with the constrained roster', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(8);
    stubMatchMedia(false, true);
    await renderGravity();
    const scene = await screen.findByTestId('gravity-scene');
    expect(scene).toHaveAttribute('data-compact', 'true');
    expect(scene).toHaveAttribute('data-roster-size', String(CONSTRAINED_BODY_COUNT));
    expect(screen.queryByLabelText(PILE_LABEL)).not.toBeInTheDocument();
  });

  it('prefers-reduced-motion forces the DOM fallback even with WebGL available', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(12);
    stubMatchMedia(true);
    await renderGravity();
    expect(screen.getByLabelText(PILE_LABEL)).toBeInTheDocument();
    expect(screen.queryByTestId('gravity-scene')).not.toBeInTheDocument();
  });

  it('carries the three-slot fresh-jobs triptych under its own heading', async () => {
    await renderGravity();
    const [earlyCareer, last24h, bigTech] = selectTriptychSlots(buildRichLandingJobs(NOW), NOW);
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

  it('renders every section from the content config', async () => {
    await renderGravity();
    for (const row of LANDING_CONTENT.comparison.rows) {
      const region = screen.getByTestId(`comparison-row-${row.id}`);
      expect(within(region).getByText(row.linkedin)).toBeInTheDocument();
      expect(within(region).getByText(row.onesecondswe)).toBeInTheDocument();
    }
    for (const feature of LANDING_CONTENT.featureMatrix.features) {
      expect(screen.getByText(feature.detail)).toBeInTheDocument();
    }
    expect(
      screen.getByRole('link', { name: LANDING_CONTENT.featureMatrix.nextUp.label })
    ).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.faq.entries[0].question)).toBeInTheDocument();
  });

  it('ends on the closing CTA with no footer', async () => {
    await renderGravity();
    expect(screen.queryByRole('contentinfo')).not.toBeInTheDocument();
    expect(screen.queryByText(LANDING_CONTENT.categoryLine)).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Why this was built' })).not.toBeInTheDocument();
  });

  it('orders the sections: triptych → LinkedIn → companies → matrix → FAQ → closer', async () => {
    await renderGravity();
    const markers = [
      screen.getByTestId('fresh-jobs-triptych'),
      screen.getByTestId('linkedin-comparison'),
      screen.getByRole('heading', { name: LANDING_CONTENT.companies.heading, level: 2 }),
      screen.getByTestId('feature-matrix'),
      screen.getByRole('heading', { name: LANDING_CONTENT.faq.heading, level: 2 }),
      screen.getByTestId('closing-cta'),
    ];
    for (let i = 1; i < markers.length; i += 1) {
      expect(
        markers[i - 1].compareDocumentPosition(markers[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
        `section ${i} is out of order`
      ).toBeTruthy();
    }
  });

  it('wraps the page in a main landmark of labelled sections', async () => {
    await renderGravity();
    const main = screen.getByRole('main');
    const sections = Array.from(main.querySelectorAll('section'));
    expect(sections.length).toBeGreaterThanOrEqual(7);
    for (const section of sections) {
      const labelledBy = section.getAttribute('aria-labelledby');
      expect(labelledBy, 'every section must point at its heading').toBeTruthy();
      expect(document.getElementById(labelledBy!), `missing heading #${labelledBy}`).not.toBeNull();
    }
  });
});
