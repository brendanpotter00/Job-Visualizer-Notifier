import { describe, it, expect } from 'vitest';
import { API_STEPS, formatUsd } from '../../../pages/LaunchRadarHowItWorksPage/content';
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

  it('prints every step body in full: exactly its JSON, nothing abridged', () => {
    for (const step of Object.values(API_STEPS)) {
      const text = linesToText(formatRequest(step.request));
      expect(text).toBe(JSON.stringify(step.request, null, 2));
      expect(text).not.toMatch(/…|\/\*/);
    }
  });

  it('shows each output schema with its field descriptions', () => {
    const text = linesToText(formatRequest(API_STEPS.monitor.request));
    expect(text).toContain('"json_schema": {');
    expect(text).toContain('"description": "Name of the company the event is about."');
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
