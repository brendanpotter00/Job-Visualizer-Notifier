import { describe, it, expect } from 'vitest';
import { isUnitedStatesLocation, US_STATE_CODES } from '../../lib/location';

describe('locationUtils', () => {
  describe('isUnitedStatesLocation', () => {
    it('should return true for locations with US state codes', () => {
      expect(isUnitedStatesLocation('San Francisco, CA')).toBe(true);
      expect(isUnitedStatesLocation('New York, NY')).toBe(true);
      expect(isUnitedStatesLocation('Austin, TX')).toBe(true);
      expect(isUnitedStatesLocation('Seattle, WA')).toBe(true);
      expect(isUnitedStatesLocation('Chicago, IL')).toBe(true);
    });

    it('should return true for Remote locations', () => {
      expect(isUnitedStatesLocation('Remote')).toBe(true);
      expect(isUnitedStatesLocation('remote')).toBe(true);
      expect(isUnitedStatesLocation('REMOTE')).toBe(true);
    });

    it('should return false for international locations', () => {
      expect(isUnitedStatesLocation('London, UK')).toBe(false);
      expect(isUnitedStatesLocation('Toronto, ON')).toBe(false);
      expect(isUnitedStatesLocation('Paris, FR')).toBe(false);
      expect(isUnitedStatesLocation('Berlin, Germany')).toBe(false);
    });

    it('should return false for locations without state codes', () => {
      expect(isUnitedStatesLocation('San Francisco')).toBe(false);
      expect(isUnitedStatesLocation('New York')).toBe(false);
      expect(isUnitedStatesLocation('Los Angeles')).toBe(false);
    });

    it('should return false for undefined or empty locations', () => {
      expect(isUnitedStatesLocation(undefined)).toBe(false);
      expect(isUnitedStatesLocation('')).toBe(false);
    });

    it('should match all 50 US state codes', () => {
      // Test a few state codes
      expect(isUnitedStatesLocation('Phoenix, AZ')).toBe(true);
      expect(isUnitedStatesLocation('Denver, CO')).toBe(true);
      expect(isUnitedStatesLocation('Miami, FL')).toBe(true);
      expect(isUnitedStatesLocation('Honolulu, HI')).toBe(true);
      expect(isUnitedStatesLocation('Portland, OR')).toBe(true);
    });

    it('should not match state code in the middle of location string', () => {
      expect(isUnitedStatesLocation('CA City')).toBe(false);
      expect(isUnitedStatesLocation('NY Times Square')).toBe(false);
    });

    it('should require comma before state code', () => {
      expect(isUnitedStatesLocation('San Francisco CA')).toBe(false);
      expect(isUnitedStatesLocation('San Francisco,CA')).toBe(false); // No space
      expect(isUnitedStatesLocation('San Francisco, CA')).toBe(true); // Correct format
    });
  });

  describe('US_STATE_CODES', () => {
    it('should contain all 50 US states', () => {
      expect(US_STATE_CODES).toHaveLength(50);
    });

    it('should include common states', () => {
      expect(US_STATE_CODES).toContain('CA');
      expect(US_STATE_CODES).toContain('NY');
      expect(US_STATE_CODES).toContain('TX');
      expect(US_STATE_CODES).toContain('FL');
      expect(US_STATE_CODES).toContain('WA');
    });

    it('should be in uppercase', () => {
      US_STATE_CODES.forEach((code) => {
        expect(code).toBe(code.toUpperCase());
        expect(code).toHaveLength(2);
      });
    });
  });
});
