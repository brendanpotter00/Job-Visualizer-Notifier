import { describe, it, expect } from 'vitest';
import {
  EMPTY_ANSWERS,
  LOCATION_PRESETS,
  ONBOARDING_QUESTIONS,
  ONBOARDING_STEP_COUNT,
  displayPlace,
  forBackend,
  isOnboardingExcludedPath,
  onboardingDocumentTitle,
  savedFiltersHaveAnswers,
  stepHasAnswer,
  toRequestAnswers,
  toggleValue,
} from '../../../components/onboarding/onboardingModel';
import { validateOnboardingResult } from '../../../features/savedFilters/savedFiltersApi';
import type { SavedFilters } from '../../../types';

const SAVED: SavedFilters = {
  recentTimeWindow: 'all',
  trendTimeWindow: '90d',
  locations: [],
  category: [],
  level: [],
  subcategory: [],
  recentActiveKeywordListId: null,
  trendActiveKeywordListId: null,
};

describe('onboardingModel', () => {
  it('offers the six preset places as canonical names, shown without ", US"', () => {
    expect(LOCATION_PRESETS).toEqual([
      'San Francisco, CA, US',
      'New York, NY, US',
      'Seattle, WA, US',
      'Austin, TX, US',
      'Remote (US)',
      'United States',
    ]);
    expect(LOCATION_PRESETS.map(displayPlace)).toEqual([
      'San Francisco, CA',
      'New York, NY',
      'Seattle, WA',
      'Austin, TX',
      'Remote (US)',
      'United States',
    ]);
    // Only a trailing ", US" goes; other countries keep theirs.
    expect(displayPlace('Toronto, ON, CA')).toBe('Toronto, ON, CA');
  });

  it('sends specialties only with Software Engineering picked', () => {
    expect(
      toRequestAnswers({ ...EMPTY_ANSWERS, category: ['growth'], subcategory: ['backend'] })
        .subcategory
    ).toEqual([]);
    expect(
      toRequestAnswers({
        ...EMPTY_ANSWERS,
        category: ['software_engineering', 'growth'],
        subcategory: ['backend'],
      }).subcategory
    ).toEqual(['backend']);
  });

  it('excludes / and /pricing, and nothing else', () => {
    expect(isOnboardingExcludedPath('/')).toBe(true);
    expect(isOnboardingExcludedPath('/pricing')).toBe(true);
    expect(isOnboardingExcludedPath('/pricing/')).toBe(true);
    expect(isOnboardingExcludedPath('/jobs')).toBe(false);
    expect(isOnboardingExcludedPath('/saved-filters')).toBe(false);
    expect(isOnboardingExcludedPath('/pricing-old')).toBe(false);
  });

  it('asks four questions, company types last', () => {
    expect(ONBOARDING_STEP_COUNT).toBe(4);
    expect(ONBOARDING_QUESTIONS).toHaveLength(4);
    expect(ONBOARDING_QUESTIONS[3]).toEqual({
      title: 'What kinds of companies do you want?',
      shortName: 'Companies',
    });
  });

  it('names each step in the tab title', () => {
    expect(onboardingDocumentTitle(0, 'onesecondswe')).toBe('Question 1 of 4: Roles | onesecondswe');
    expect(onboardingDocumentTitle(2, 'onesecondswe')).toBe('Question 3 of 4: Places | onesecondswe');
    expect(onboardingDocumentTitle(3, 'onesecondswe')).toBe(
      'Question 4 of 4: Companies | onesecondswe'
    );
  });

  it('knows whether a step or the saved filters carry an answer', () => {
    const draft = { ...EMPTY_ANSWERS, level: ['mid'] };
    expect(stepHasAnswer(draft, 0)).toBe(false);
    expect(stepHasAnswer(draft, 1)).toBe(true);
    expect(stepHasAnswer(draft, 2)).toBe(false);
    expect(stepHasAnswer(draft, 3)).toBe(false);
    expect(stepHasAnswer({ ...EMPTY_ANSWERS, companyCategory: ['big_tech'] }, 3)).toBe(true);
    expect(savedFiltersHaveAnswers(SAVED)).toBe(false);
    expect(savedFiltersHaveAnswers({ ...SAVED, locations: ['Remote (US)'] })).toBe(true);
    expect(savedFiltersHaveAnswers({ ...SAVED, companyCategory: [] })).toBe(false);
    expect(savedFiltersHaveAnswers({ ...SAVED, companyCategory: ['ai_labs'] })).toBe(true);
  });

  it('sends the company types as answered', () => {
    expect(EMPTY_ANSWERS.companyCategory).toEqual([]);
    expect(
      toRequestAnswers({ ...EMPTY_ANSWERS, companyCategory: ['fintech'] }).companyCategory
    ).toEqual(['fintech']);
  });

  it('shapes the body for an older backend: no company types, step clamped to 3', () => {
    const body = {
      ...toRequestAnswers({ ...EMPTY_ANSWERS, companyCategory: ['fintech'] }),
      skipped: false,
      step: 4 as const,
    };
    expect(forBackend(body, true)).toBe(body);
    const legacy = forBackend(body, false);
    expect(legacy).not.toHaveProperty('companyCategory');
    expect(legacy.step).toBe(3);
    expect(forBackend({ ...body, step: 2 }, false).step).toBe(2);
    // The input is not mutated.
    expect(body.companyCategory).toEqual(['fintech']);
  });

  it('toggles a value without duplicating it', () => {
    expect(toggleValue(['a'], 'b', true)).toEqual(['a', 'b']);
    expect(toggleValue(['a', 'b'], 'b', true)).toEqual(['a', 'b']);
    expect(toggleValue(['a', 'b'], 'a', false)).toEqual(['b']);
  });
});

describe('validateOnboardingResult', () => {
  it('accepts the server answer and normalizes its saved filters', () => {
    const { subcategory: _omitted, ...legacy } = SAVED;
    const result = validateOnboardingResult({
      onboardingCompletedAt: '2026-11-22T10:00:00+00:00',
      savedFilters: legacy,
    });
    expect(result.onboardingCompletedAt).toBe('2026-11-22T10:00:00+00:00');
    expect(result.savedFilters.subcategory).toEqual([]);
  });

  it('rejects a body without a stamp or with malformed saved filters', () => {
    expect(() => validateOnboardingResult({ savedFilters: SAVED })).toThrow(/onboardingCompletedAt/);
    expect(() =>
      validateOnboardingResult({ onboardingCompletedAt: 'x', savedFilters: { ...SAVED, level: 'mid' } })
    ).toThrow(/level/);
    expect(() => validateOnboardingResult(null)).toThrow(/not an object/);
  });
});
