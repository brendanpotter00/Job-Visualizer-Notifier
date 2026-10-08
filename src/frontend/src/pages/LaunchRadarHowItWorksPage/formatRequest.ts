// Pretty-prints a request body as JSON lines with an indent level and typed
// tokens, so RequestBody can colour keys and values and give each wrapped line
// a hanging indent. Pure: no React here.
import { SchemaFields, type RequestValue } from './content';

export type TokenKind = 'key' | 'string' | 'literal' | 'punct' | 'comment';

export interface Token {
  kind: TokenKind;
  text: string;
}

export interface Line {
  /** Nesting depth; each level is two characters wide. */
  depth: number;
  tokens: Token[];
}

/** How many field names share a line in a schema comment. */
const FIELDS_PER_LINE = 3;

function scalarToken(value: string | number | boolean | null): Token {
  return typeof value === 'string'
    ? { kind: 'string', text: JSON.stringify(value) }
    : { kind: 'literal', text: String(value) };
}

function emit(value: RequestValue, depth: number, lead: Token[], trailingComma: boolean): Line[] {
  const comma: Token[] = trailingComma ? [{ kind: 'punct', text: ',' }] : [];

  if (value instanceof SchemaFields) {
    const rows: string[] = [];
    for (let i = 0; i < value.fields.length; i += FIELDS_PER_LINE) {
      rows.push(value.fields.slice(i, i + FIELDS_PER_LINE).join(', '));
    }
    return [
      { depth, tokens: [...lead, { kind: 'punct', text: '{' }] },
      {
        depth: depth + 1,
        tokens: [{ kind: 'comment', text: `/* ${value.fields.length} fields:` }],
      },
      ...rows.map((row, i) => ({
        depth: depth + 1,
        tokens: [
          { kind: 'comment' as const, text: `   ${row}${i < rows.length - 1 ? ',' : ' */'}` },
        ],
      })),
      { depth, tokens: [{ kind: 'punct', text: '}' }, ...comma] },
    ];
  }

  if (value === null || typeof value !== 'object') {
    return [{ depth, tokens: [...lead, scalarToken(value), ...comma] }];
  }

  const isArray = Array.isArray(value);
  const entries: [string | null, RequestValue][] = isArray
    ? (value as readonly RequestValue[]).map((v) => [null, v])
    : Object.entries(value as { readonly [key: string]: RequestValue });
  const [open, close] = isArray ? ['[', ']'] : ['{', '}'];
  if (entries.length === 0) {
    return [{ depth, tokens: [...lead, { kind: 'punct', text: open + close }, ...comma] }];
  }
  return [
    { depth, tokens: [...lead, { kind: 'punct', text: open }] },
    ...entries.flatMap(([key, child], i) =>
      emit(
        child,
        depth + 1,
        key === null
          ? []
          : [
              { kind: 'key', text: JSON.stringify(key) },
              { kind: 'punct', text: ': ' },
            ],
        i < entries.length - 1
      )
    ),
    { depth, tokens: [{ kind: 'punct', text: close }, ...comma] },
  ];
}

/** The body as JSON lines, two spaces per level, schemas as a comment block. */
export function formatRequest(value: RequestValue): Line[] {
  return emit(value, 0, [], false);
}

/** The plain text of the lines, indented with spaces (for copying and tests). */
export function linesToText(lines: Line[]): string {
  return lines
    .map((line) => '  '.repeat(line.depth) + line.tokens.map((t) => t.text).join(''))
    .join('\n');
}
