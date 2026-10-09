import { useMemo } from 'react';
import Box from '@mui/material/Box';
import { RESPONSIVE } from '../../../config/responsive';
import type { RequestValue } from '../content';
import { formatRequest, type TokenKind } from '../formatRequest';

const TOKEN_SX: Record<TokenKind, object> = {
  key: { color: 'text.primary', fontWeight: 600 },
  string: { color: 'grey.800' },
  literal: { color: 'text.primary' },
  punct: { color: 'text.disabled' },
};

/**
 * A request body as readable JSON. Each line is its own block with a hanging
 * indent, so a long string wraps under itself instead of back to the left edge.
 */
export function RequestBody({ value }: { value: RequestValue }) {
  const lines = useMemo(() => formatRequest(value), [value]);
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: 1.5,
        bgcolor: 'background.paper',
        borderRadius: 1,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: RESPONSIVE.launchRadarHowItWorks.codeFontSize,
        lineHeight: 1.55,
        whiteSpace: 'pre-wrap',
        overflowWrap: 'anywhere',
      }}
    >
      {lines.map((line, i) => (
        <Box
          // The lines are a fixed rendering of a constant body; they never reorder.
          key={i}
          component="span"
          sx={{ display: 'block', pl: `${line.depth * 2 + 2}ch`, textIndent: '-2ch' }}
        >
          {line.tokens.map((token, j) => (
            <Box key={j} component="span" sx={TOKEN_SX[token.kind]}>
              {token.text}
            </Box>
          ))}
        </Box>
      ))}
    </Box>
  );
}
