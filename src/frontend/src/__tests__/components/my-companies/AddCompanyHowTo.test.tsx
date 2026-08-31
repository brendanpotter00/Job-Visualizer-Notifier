import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import { renderWithProviders } from '../../../test/testUtils';
import {
  AddCompanyHowTo,
  HOW_IT_WORKS_VIDEO_SRC,
} from '../../../components/my-companies/AddCompanyHowTo';

describe('AddCompanyHowTo', () => {
  it('renders three numbered steps and nothing else', async () => {
    // No heading, no lede, no per-step subtext, no caption. All four were cut ("we don't
    // need all this subtext"), and the trim has to hold in the component both triggers
    // share — trimming one render and not the other would ship two versions of it.
    renderWithProviders(<AddCompanyHowTo />);

    const list = screen.getByRole('list');
    const steps = within(list).getAllByRole('listitem');
    expect(steps).toHaveLength(3);
    expect(steps[0]).toHaveTextContent('Open their careers page');
    expect(steps[1]).toHaveTextContent('Copy the link');
    expect(steps[2]).toHaveTextContent('Paste it in the box above');
  });

  it('carries an explicit role="list", which WebKit needs', async () => {
    // An <ol> with `list-style: none` loses its list role in Safari and iOS VoiceOver,
    // and the numbering — which lives in aria-hidden glyphs — goes with it. The explicit
    // role is what stops this announcing as three loose paragraphs.
    renderWithProviders(<AddCompanyHowTo />);

    const list = screen.getByRole('list');
    expect(list.tagName).toBe('OL');
    expect(list).toHaveAttribute('role', 'list');
  });

  it('hides the digits from screen readers, since the list already numbers itself', () => {
    renderWithProviders(<AddCompanyHowTo />);

    const steps = within(screen.getByRole('list')).getAllByRole('listitem');
    steps.forEach((step, index) => {
      const digit = step.querySelector('[aria-hidden="true"]');
      expect(digit).not.toBeNull();
      expect(digit).toHaveTextContent(String(index + 1));
    });
  });

  // ── the video slot ──────────────────────────────────────────────────────────
  //
  // "I want it to be easy to implement when I have a video, but this is going to ship
  // without a video for now." So the layout is composed BOTH ways, and the empty case
  // draws nothing at all rather than a grey rectangle promising something that does not
  // exist.

  it('ships with no video configured', () => {
    // If this ever fails, the video landed — and the "not LinkedIn or Indeed" clause in
    // `ResolveUrlForm`'s helper (which exists only because there is no video) can go.
    expect(HOW_IT_WORKS_VIDEO_SRC).toBeNull();
  });

  it('renders NOTHING in the video space while no video is configured', () => {
    renderWithProviders(<AddCompanyHowTo videoSrc={null} />);

    expect(screen.queryByTestId('add-company-how-to-video')).not.toBeInTheDocument();
    expect(document.querySelector('figure')).toBeNull();
    // …and the steps are still there, so the block stands on its own.
    expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(3);
  });

  it('renders the video the moment a src is configured, under the same steps', () => {
    renderWithProviders(<AddCompanyHowTo videoSrc="/how-it-works.mp4" />);

    const video = screen.getByTestId('add-company-how-to-video');
    expect(video).toHaveAttribute('src', '/how-it-works.mp4');
    // Described for anyone who cannot watch it.
    expect(video).toHaveAccessibleName(/careers page/i);
    expect(within(screen.getByRole('list')).getAllByRole('listitem')).toHaveLength(3);
  });

  it('names the empty list for a screen reader without drawing anything', () => {
    // Cutting the visible "No companies yet" heading left a screen-reader user hearing
    // "Companies you're tracking" followed by three instructions, never told the list was
    // empty. This restores the fact and only the fact.
    renderWithProviders(<AddCompanyHowTo srOnlyLine="No companies yet" />);

    const line = screen.getByText('No companies yet');
    expect(line).toBeInTheDocument();
    // MUI's `visuallyHidden`: clipped to a 1px box, not `display: none` (which would take
    // it out of the accessibility tree along with the rest).
    expect(line).toHaveStyle({ position: 'absolute', width: '1px', height: '1px' });
  });

  it('says nothing extra when no line is passed', () => {
    renderWithProviders(<AddCompanyHowTo />);
    expect(screen.queryByText('No companies yet')).not.toBeInTheDocument();
  });
});
