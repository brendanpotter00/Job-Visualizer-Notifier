import { describe, it, expect } from 'vitest';
import type {
  AttemptOutcome,
  CustomCompanyLiveStatus,
} from '../../../features/admin/adminApi';
import {
  ATTEMPT_OUTCOME_OPTIONS,
  HEALTH_STATE_OPTIONS,
  attemptOutcomeChip,
  healthStateChip,
  liveStatusChip,
} from '../../../pages/AdminCustomCompaniesPage/statusChips';

/**
 * The whole matrix, with one claim pinned above all others: `variant: 'filled'`
 * means BAD and `variant: 'outlined'` means good or neutral. That inversion is
 * this repo's severity signal and the single easiest thing to get backwards —
 * a filled green "added" chip would shout at a success on every row.
 */

const GOOD_OR_NEUTRAL_LIVE: CustomCompanyLiveStatus[] = ['live'];
const BAD_LIVE: CustomCompanyLiveStatus[] = ['stale', 'failing', 'never_harvested', 'orphan'];

const GOOD_OR_NEUTRAL_OUTCOMES: AttemptOutcome[] = ['added', 'already_public', 'pending'];
const BAD_OUTCOMES: AttemptOutcome[] = [
  'stuck',
  'refused',
  'unsupported',
  'empty',
  'probe_failed',
];

describe('statusChips', () => {
  describe('liveStatusChip', () => {
    it('maps every live status to its documented label and colour', () => {
      expect(liveStatusChip('live')).toEqual({
        label: 'Live',
        color: 'success',
        variant: 'outlined',
      });
      expect(liveStatusChip('stale')).toEqual({
        label: 'Stale',
        color: 'warning',
        variant: 'filled',
      });
      expect(liveStatusChip('failing')).toEqual({
        label: 'Failing',
        color: 'error',
        variant: 'filled',
      });
      expect(liveStatusChip('never_harvested')).toEqual({
        label: 'Never harvested',
        color: 'warning',
        variant: 'filled',
      });
      expect(liveStatusChip('orphan')).toEqual({
        label: 'Orphan',
        color: 'warning',
        variant: 'filled',
      });
    });

    it('renders good/neutral outlined and bad filled', () => {
      for (const status of GOOD_OR_NEUTRAL_LIVE) {
        expect(liveStatusChip(status).variant).toBe('outlined');
      }
      for (const status of BAD_LIVE) {
        expect(liveStatusChip(status).variant).toBe('filled');
      }
    });

    it('echoes an unrecognised wire value rather than rendering a blank chip', () => {
      const chip = liveStatusChip('teleported' as CustomCompanyLiveStatus);
      expect(chip.label).toBe('teleported');
      expect(chip.variant).toBe('outlined');
    });
  });

  describe('attemptOutcomeChip', () => {
    it('maps all eight outcomes to non-empty labels', () => {
      for (const outcome of [...GOOD_OR_NEUTRAL_OUTCOMES, ...BAD_OUTCOMES]) {
        expect(attemptOutcomeChip(outcome).label.length).toBeGreaterThan(0);
      }
      expect(attemptOutcomeChip('already_public').label).toBe('already public');
      expect(attemptOutcomeChip('probe_failed').label).toBe('probe failed');
    });

    it('renders good/neutral outlined and bad filled', () => {
      for (const outcome of GOOD_OR_NEUTRAL_OUTCOMES) {
        expect(attemptOutcomeChip(outcome).variant).toBe('outlined');
      }
      for (const outcome of BAD_OUTCOMES) {
        expect(attemptOutcomeChip(outcome).variant).toBe('filled');
      }
    });

    it('keeps an in-flight "pending" neutral and an over-grace "stuck" alarming', () => {
      expect(attemptOutcomeChip('pending').color).toBe('default');
      expect(attemptOutcomeChip('pending').variant).toBe('outlined');
      expect(attemptOutcomeChip('stuck').color).toBe('warning');
      expect(attemptOutcomeChip('stuck').variant).toBe('filled');
    });
  });

  describe('healthStateChip', () => {
    it('maps the five known health states', () => {
      expect(healthStateChip('healthy')).toEqual({
        label: 'healthy',
        color: 'success',
        variant: 'outlined',
      });
      expect(healthStateChip('unverified')).toEqual({
        label: 'unverified',
        color: 'warning',
        variant: 'filled',
      });
      expect(healthStateChip('discovering')).toEqual({
        label: 'discovering',
        color: 'info',
        variant: 'outlined',
      });
      expect(healthStateChip('quarantined')).toEqual({
        label: 'quarantined',
        color: 'error',
        variant: 'filled',
      });
      expect(healthStateChip('refused')).toEqual({
        label: 'refused',
        color: 'error',
        variant: 'filled',
      });
    });

    it('renders an em dash for null and echoes an unknown code verbatim', () => {
      expect(healthStateChip(null).label).toBe('—');
      expect(healthStateChip('sleeping').label).toBe('sleeping');
      expect(healthStateChip('sleeping').variant).toBe('outlined');
    });
  });

  describe('dropdown options', () => {
    it('offers every outcome, labelled exactly as the chip labels it', () => {
      expect(ATTEMPT_OUTCOME_OPTIONS).toHaveLength(8);
      for (const option of ATTEMPT_OUTCOME_OPTIONS) {
        expect(option.label).toBe(attemptOutcomeChip(option.slug as AttemptOutcome).label);
      }
    });

    it('offers every health state, including ones with zero rows today', () => {
      expect(HEALTH_STATE_OPTIONS.map((o) => o.slug)).toEqual([
        'discovering',
        'unverified',
        'healthy',
        'quarantined',
        'refused',
      ]);
    });
  });
});
