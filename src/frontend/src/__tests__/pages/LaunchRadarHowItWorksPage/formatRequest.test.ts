import { describe, it, expect } from 'vitest';
import {
  API_STEPS,
  SchemaFields,
  formatUsd,
} from '../../../pages/LaunchRadarHowItWorksPage/content';
import { formatRequest, linesToText } from '../../../pages/LaunchRadarHowItWorksPage/formatRequest';

describe('formatRequest', () => {
  it('prints nested objects and arrays like JSON.stringify with two-space indents', () => {
    const value = { a: 1, b: ['x', true, null], c: { d: 'e' }, f: [], g: {} };
    expect(linesToText(formatRequest(value))).toBe(JSON.stringify(value, null, 2));
  });

  it('gives every line its nesting depth and types its tokens', () => {
    const lines = formatRequest({ outer: { inner: 'v' } });
    expect(lines.map((l) => l.depth)).toEqual([0, 1, 2, 1, 0]);
    expect(lines[2].tokens).toEqual([
      { kind: 'key', text: '"inner"' },
      { kind: 'punct', text: ': ' },
      { kind: 'string', text: '"v"' },
    ]);
  });

  it('shows an output schema as a comment that lists its fields, three to a line', () => {
    const text = linesToText(
      formatRequest({ json_schema: new SchemaFields('a', 'b', 'c', 'd'), next: 1 })
    );
    expect(text).toBe(
      [
        '{',
        '  "json_schema": {',
        '    /* 4 fields:',
        '       a, b, c,',
        '       d */',
        '  },',
        '  "next": 1',
        '}',
      ].join('\n')
    );
  });

  it('formats every step body without throwing, ending on its closing brace', () => {
    for (const step of Object.values(API_STEPS)) {
      const lines = formatRequest(step.request);
      const last = lines[lines.length - 1];
      expect(last.tokens.map((t) => t.text).join('')).toBe('}');
    }
  });
});

describe('formatUsd', () => {
  it('shows whole cents with two decimals and fractions of a cent with three', () => {
    expect(formatUsd(0.1)).toBe('$0.10');
    expect(formatUsd(0.28)).toBe('$0.28');
    expect(formatUsd(0.025)).toBe('$0.025');
    expect(formatUsd(0.005)).toBe('$0.005');
  });
});
