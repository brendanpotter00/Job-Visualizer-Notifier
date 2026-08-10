import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen } from '@testing-library/react';
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
  it('renders the terse hero h1 with the source subheadline and primary CTA', () => {
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

  it('keeps Signal-skeleton sections below the hero: stats, logo wall, FAQ, footer', () => {
    renderDrift();
    expect(screen.getByText(/tracked in the past 24 hours/)).toBeInTheDocument();
    expect(screen.getByLabelText('Companies tracked by onesecondswe')).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.faq[0].question)).toBeInTheDocument();
    expect(screen.getByText(LANDING_CONTENT.footer.tagline)).toBeInTheDocument();
  });
});
