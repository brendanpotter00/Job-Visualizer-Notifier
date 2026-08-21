import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import { DriftPrototype } from '../../../pages/AdminLandingPrototypesPage/prototypes/DriftPrototype/DriftPrototype';
import { detectWebGLSupport } from '../../../pages/AdminLandingPrototypesPage/prototypes/shared3d/detectWebGL';
import { MIN_JOB_DOTS } from '../../../pages/AdminLandingPrototypesPage/prototypes/DriftPrototype/particlesConfig';
import { LANDING_CONTENT } from '../../../pages/AdminLandingPrototypesPage/content';
import { buildMockJobs, MOCK_STATS } from '../../../pages/AdminLandingPrototypesPage/mockData';

// Mock boundary = the scene module (<Canvas> throws in jsdom; three stays out
// of the test process, mirroring the lazy-chunk isolation at runtime).
vi.mock(
  '../../../pages/AdminLandingPrototypesPage/prototypes/DriftPrototype/DriftScene',
  () => ({
    default: (props: { config: { jobs: { count: number } }; maxDpr: number }) => (
      <div
        data-testid="drift-scene"
        data-job-dots={props.config.jobs.count}
        data-max-dpr={props.maxDpr}
      />
    ),
  })
);

vi.mock('../../../pages/AdminLandingPrototypesPage/prototypes/shared3d/detectWebGL', () => ({
  detectWebGLSupport: vi.fn(() => false),
}));

const NOW = new Date('2026-08-09T18:00:00Z').getTime();
const CAPTION = 'Every dot is a job posted today.';

function renderDrift() {
  return renderWithProviders(
    <DriftPrototype
      content={LANDING_CONTENT}
      jobs={buildMockJobs(NOW)}
      stats={MOCK_STATS}
      sparse={false}
      now={NOW}
    />,
    { initialEntries: ['/admin/landing-prototypes?proto=drift'] }
  );
}

function stubCores(cores: number) {
  Object.defineProperty(window.navigator, 'hardwareConcurrency', {
    value: cores,
    configurable: true,
  });
}

afterEach(() => {
  Reflect.deleteProperty(window.navigator, 'hardwareConcurrency');
});

describe('DriftPrototype', () => {
  it('opens with the shared landing header above the clipped hero', () => {
    renderDrift();
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

  it('renders the terse hero h1 with the source subheadline and both CTAs', () => {
    renderDrift();
    const h1 = screen.getByRole('heading', { level: 1 });
    expect(h1).toHaveTextContent('Jobs at the source.');
    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1);
    expect(
      screen.getByText(LANDING_CONTENT.heroVariants.source.subheadline)
    ).toBeInTheDocument();
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

  it('keeps the data claim as DOM text on every tier', () => {
    renderDrift();
    expect(screen.getByText(CAPTION)).toBeInTheDocument();
  });

  it('fallback tier (no WebGL): static gradient-dot backdrop, scene never mounts', () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(false);
    renderDrift();
    expect(screen.getByTestId('drift-dot-backdrop')).toBeInTheDocument();
    expect(screen.queryByTestId('drift-scene')).not.toBeInTheDocument();
  });

  it('full tier: lazy-mounts the scene; the data layer floors at MIN_JOB_DOTS', async () => {
    vi.mocked(detectWebGLSupport).mockReturnValue(true);
    stubCores(12);
    renderDrift();
    const scene = await screen.findByTestId('drift-scene');
    // The rich fixture carries 10 jobs <24h — below the floor, so the layer
    // pins at MIN_JOB_DOTS (the "never looks empty" guarantee).
    expect(scene).toHaveAttribute('data-job-dots', String(MIN_JOB_DOTS));
    expect(scene).toHaveAttribute('data-max-dpr', '2');
    expect(screen.queryByTestId('drift-dot-backdrop')).not.toBeInTheDocument();
    expect(screen.getByText(CAPTION)).toBeInTheDocument();
  });

  // Drift never carried a jobs rail, so the stats strip left nothing behind:
  // no rotating card here either (that lives in Signal and Gravity).
  it('keeps Signal-skeleton sections below the hero: logo wall, FAQ, footer', () => {
    renderDrift();
    expect(screen.getByLabelText('Companies tracked by onesecondswe')).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.faq[0].question)).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.footer.tagline)).toBeInTheDocument();
    expect(screen.queryByText(/tracked in the past 24 hours/)).not.toBeInTheDocument();
    expect(screen.queryByTestId('rotating-job-card')).not.toBeInTheDocument();
  });
});
