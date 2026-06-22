import { describe, it, expect } from 'vitest';
import { serializeParamsWithEncodedSpaces } from '../../../features/savedFilters/savedFiltersApi';

describe('serializeParamsWithEncodedSpaces (Bug #1: "San Fran" location search)', () => {
  it('encodes a space as %20, never as +', () => {
    const qs = serializeParamsWithEncodedSpaces({ q: 'San Fran' });
    expect(qs).toBe('q=San%20Fran');
    expect(qs).not.toContain('+');
  });

  it('encodes every space in a multi-word query', () => {
    expect(serializeParamsWithEncodedSpaces({ q: 'New York City' })).toBe('q=New%20York%20City');
  });

  it('keeps numeric and boolean params alongside the encoded query', () => {
    const qs = serializeParamsWithEncodedSpaces({ q: 'San Fran', limit: 20, openOnly: true });
    expect(qs).toContain('q=San%20Fran');
    expect(qs).toContain('limit=20');
    expect(qs).toContain('openOnly=true');
    expect(qs).not.toContain('+');
  });

  it('omits undefined params', () => {
    expect(serializeParamsWithEncodedSpaces({ q: 'austin', limit: undefined })).toBe('q=austin');
  });

  it('leaves a single-word query untouched (the case that already worked)', () => {
    expect(serializeParamsWithEncodedSpaces({ q: 'San' })).toBe('q=San');
  });
});
