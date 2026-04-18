import { describe, it, expect } from 'vitest';
import { transformEightfoldJob } from '../../../api/transformers/eightfoldTransformer';
import type { EightfoldJobPosition } from '../../../api/types';

describe('transformEightfoldJob', () => {
  const companyId = 'netflix';

  function basePosition(
    overrides: Partial<EightfoldJobPosition> = {}
  ): EightfoldJobPosition {
    return {
      id: 790315489399,
      name: 'Administrative Assistant, Post Services',
      location: 'Los Angeles,California,United States of America',
      locations: ['Los Angeles,California,United States of America'],
      department: 'Administration',
      business_unit: 'Streaming',
      t_update: 1776297600,
      t_create: 1776297600,
      ats_job_id: 'JR40083',
      display_job_id: 'JR40083',
      type: 'ATS',
      job_description: '',
      work_location_option: 'onsite',
      canonicalPositionUrl:
        'https://explore.jobs.netflix.net/careers/job/790315489399',
      isPrivate: false,
      ...overrides,
    };
  }

  describe('Basic Transformation', () => {
    it('transforms a full Netflix-shaped position', () => {
      const raw = basePosition();
      const result = transformEightfoldJob(raw, companyId);

      expect(result).toMatchObject({
        id: '790315489399',
        source: 'eightfold',
        company: 'netflix',
        title: 'Administrative Assistant, Post Services',
        department: 'Administration',
        location: 'Los Angeles, California, United States of America',
        isRemote: false,
        url: 'https://explore.jobs.netflix.net/careers/job/790315489399',
        tags: ['JR40083'],
      });
      // t_create 1776297600 (unix seconds) → 2026-04-16T00:00:00Z
      expect(result.createdAt).toBe('2026-04-16T00:00:00.000Z');
      expect(result.raw).toBe(raw);
    });

    it('coerces numeric id to string', () => {
      const raw = basePosition({ id: 42 });
      expect(transformEightfoldJob(raw, companyId).id).toBe('42');
    });
  });

  describe('ID Fallback', () => {
    it('falls back to ats_job_id when id is missing', () => {
      // Using `as any` because the plan allows missing id in the raw shape
      const raw = basePosition({ ats_job_id: 'REQ-111' });
      // Force removal of id
      delete (raw as Partial<EightfoldJobPosition>).id;
      const result = transformEightfoldJob(raw as EightfoldJobPosition, companyId);
      expect(result.id).toBe('REQ-111');
    });

    it('falls back to display_job_id when id and ats_job_id are missing', () => {
      const raw = basePosition({
        ats_job_id: undefined,
        display_job_id: 'DISP-222',
      });
      delete (raw as Partial<EightfoldJobPosition>).id;
      const result = transformEightfoldJob(raw as EightfoldJobPosition, companyId);
      expect(result.id).toBe('DISP-222');
    });

    it('falls back to empty string when all id sources are missing', () => {
      const raw = basePosition({
        ats_job_id: undefined,
        display_job_id: undefined,
      });
      delete (raw as Partial<EightfoldJobPosition>).id;
      const result = transformEightfoldJob(raw as EightfoldJobPosition, companyId);
      expect(result.id).toBe('');
    });
  });

  describe('Location Handling', () => {
    it('splits, trims, and rejoins with ", "', () => {
      const raw = basePosition({ location: 'Austin,Texas,United States' });
      expect(transformEightfoldJob(raw, companyId).location).toBe(
        'Austin, Texas, United States'
      );
    });

    it('uses locations[0] when top-level location is empty', () => {
      const raw = basePosition({
        location: '',
        locations: ['New York,New York,United States'],
      });
      expect(transformEightfoldJob(raw, companyId).location).toBe(
        'New York, New York, United States'
      );
    });

    it('returns undefined when both location and locations are absent', () => {
      const raw = basePosition({ location: undefined, locations: undefined });
      expect(transformEightfoldJob(raw, companyId).location).toBeUndefined();
    });

    it('collapses extra commas and whitespace', () => {
      const raw = basePosition({ location: ' Paris , ,  France ' });
      expect(transformEightfoldJob(raw, companyId).location).toBe('Paris, France');
    });
  });

  describe('Date Parsing', () => {
    it('treats t_create as unix seconds and returns ISO 8601', () => {
      const raw = basePosition({ t_create: 1700000000 });
      expect(transformEightfoldJob(raw, companyId).createdAt).toBe(
        new Date(1700000000 * 1000).toISOString()
      );
    });

    it('falls back to t_update when t_create is missing', () => {
      const raw = basePosition({ t_create: undefined, t_update: 1700000100 });
      expect(transformEightfoldJob(raw, companyId).createdAt).toBe(
        new Date(1700000100 * 1000).toISOString()
      );
    });

    it('falls back to current time when both t_create and t_update are missing', () => {
      const raw = basePosition({ t_create: undefined, t_update: undefined });
      const before = Date.now();
      const result = transformEightfoldJob(raw, companyId);
      const after = Date.now();
      const created = new Date(result.createdAt).getTime();
      expect(created).toBeGreaterThanOrEqual(before);
      expect(created).toBeLessThanOrEqual(after);
    });
  });

  describe('Remote Detection', () => {
    it('isRemote=true only when work_location_option is "remote"', () => {
      expect(
        transformEightfoldJob(
          basePosition({ work_location_option: 'remote' }),
          companyId
        ).isRemote
      ).toBe(true);
    });

    it('isRemote=false for "onsite"', () => {
      expect(
        transformEightfoldJob(
          basePosition({ work_location_option: 'onsite' }),
          companyId
        ).isRemote
      ).toBe(false);
    });

    it('isRemote=false for "hybrid"', () => {
      expect(
        transformEightfoldJob(
          basePosition({ work_location_option: 'hybrid' }),
          companyId
        ).isRemote
      ).toBe(false);
    });

    it('isRemote=false when work_location_option is null', () => {
      expect(
        transformEightfoldJob(
          basePosition({ work_location_option: null }),
          companyId
        ).isRemote
      ).toBe(false);
    });
  });

  describe('Department Handling', () => {
    it('preserves a non-empty department', () => {
      expect(
        transformEightfoldJob(basePosition({ department: 'Engineering' }), companyId)
          .department
      ).toBe('Engineering');
    });

    it('coerces null department to undefined', () => {
      expect(
        transformEightfoldJob(basePosition({ department: null }), companyId).department
      ).toBeUndefined();
    });
  });

  describe('Tags', () => {
    it('prefers display_job_id for the tag', () => {
      const raw = basePosition({
        display_job_id: 'DISP-1',
        ats_job_id: 'ATS-1',
      });
      expect(transformEightfoldJob(raw, companyId).tags).toEqual(['DISP-1']);
    });

    it('falls back to ats_job_id when display_job_id is missing', () => {
      const raw = basePosition({
        display_job_id: undefined,
        ats_job_id: 'ATS-1',
      });
      expect(transformEightfoldJob(raw, companyId).tags).toEqual(['ATS-1']);
    });

    it('returns undefined tags when both ids are missing', () => {
      const raw = basePosition({
        display_job_id: undefined,
        ats_job_id: undefined,
      });
      expect(transformEightfoldJob(raw, companyId).tags).toBeUndefined();
    });
  });

  describe('Privacy & Raw Preservation', () => {
    it('does NOT filter private jobs — the transformer preserves them', () => {
      const raw = basePosition({ isPrivate: true });
      const result = transformEightfoldJob(raw, companyId);
      expect(result.id).toBe('790315489399');
      expect(result.raw).toBe(raw);
    });

    it('keeps reference equality of raw for debuggability', () => {
      const raw = basePosition();
      expect(transformEightfoldJob(raw, companyId).raw).toBe(raw);
    });
  });
});
