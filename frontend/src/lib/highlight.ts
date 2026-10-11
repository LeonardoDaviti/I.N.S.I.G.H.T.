/**
 * A small syntax highlighter for the blog's code excerpts. Monochrome by design
 * (design principle P2): tokens differ by weight and tone, never by hue, so the
 * highlighting follows the dark/light theme like everything else.
 *
 * It knows only the languages the posts quote. Anything it does not recognise
 * stays plain text, which is always a safe rendering.
 */

export type Lang = 'python' | 'ts' | 'dockerfile' | 'diff' | 'comment' | 'text';

export type TokenKind = 'plain' | 'keyword' | 'name' | 'string' | 'number' | 'comment' | 'decorator' | 'constant' | 'added' | 'removed';

export interface Token {
  kind: TokenKind;
  text: string;
}

const PYTHON_KEYWORDS = new Set([
  'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue', 'def', 'del', 'elif', 'else', 'except', 'finally',
  'for', 'from', 'global', 'if', 'import', 'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try',
  'while', 'with', 'yield',
]);
const PYTHON_CONSTANTS = new Set(['True', 'False', 'None', 'self']);

const TS_KEYWORDS = new Set([
  'async', 'await', 'break', 'case', 'catch', 'class', 'const', 'continue', 'default', 'else', 'export', 'extends', 'finally',
  'for', 'from', 'function', 'if', 'import', 'in', 'instanceof', 'interface', 'let', 'new', 'of', 'return', 'switch', 'throw',
  'try', 'type', 'typeof', 'var', 'while',
]);
const TS_CONSTANTS = new Set(['true', 'false', 'null', 'undefined', 'this']);

const DOCKER_INSTRUCTIONS = /^(\s*)(FROM|RUN|COPY|ADD|WORKDIR|ENV|ARG|EXPOSE|ENTRYPOINT|CMD|USER|LABEL|VOLUME|HEALTHCHECK|SHELL)\b/i;

/** The keywords after which the next identifier is the name being defined. */
const DEFINERS = new Set(['def', 'class', 'function', 'interface', 'type']);

interface Grammar {
  comment: RegExp;
  string: RegExp;
  keywords: Set<string>;
  constants: Set<string>;
  decorators: boolean;
}

const PYTHON: Grammar = {
  comment: /#.*/y,
  string: /[rbfu]{0,2}("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')/y,
  keywords: PYTHON_KEYWORDS,
  constants: PYTHON_CONSTANTS,
  decorators: true,
};

const TS: Grammar = {
  comment: /\/\/.*|\/\*[\s\S]*?\*\//y,
  string: /"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`/y,
  keywords: TS_KEYWORDS,
  constants: TS_CONSTANTS,
  decorators: false,
};

const SHELL: Grammar = {
  comment: /#.*/y,
  string: /"(?:\\.|[^"\\\n])*"|'[^'\n]*'/y,
  keywords: new Set(),
  constants: new Set(),
  decorators: false,
};

const WORD = /[A-Za-z_$][\w$]*/y;
const NUMBER = /\b\d[\d_]*(?:\.\d+)?\b/y;
const DECORATOR = /@[A-Za-z_][\w.]*/y;

function at(re: RegExp, source: string, index: number): string | null {
  re.lastIndex = index;
  const match = re.exec(source);
  return match ? match[0] : null;
}

/** Tokens for one grammar; adjacent plain characters are merged into one token. */
function scan(source: string, grammar: Grammar): Token[] {
  const tokens: Token[] = [];
  const push = (kind: TokenKind, text: string) => {
    const last = tokens[tokens.length - 1];
    if (kind === 'plain' && last?.kind === 'plain') last.text += text;
    else tokens.push({ kind, text });
  };
  let defining = false;
  let i = 0;
  while (i < source.length) {
    const comment = at(grammar.comment, source, i);
    if (comment) { push('comment', comment); i += comment.length; continue; }
    const string = at(grammar.string, source, i);
    if (string) { push('string', string); i += string.length; continue; }
    if (grammar.decorators) {
      const decorator = at(DECORATOR, source, i);
      if (decorator && (i === 0 || /\s/.test(source[i - 1]))) { push('decorator', decorator); i += decorator.length; continue; }
    }
    const word = at(WORD, source, i);
    if (word) {
      if (defining) { push('name', word); defining = false; }
      else if (grammar.keywords.has(word)) { push('keyword', word); defining = DEFINERS.has(word); }
      else if (grammar.constants.has(word)) push('constant', word);
      else push('plain', word);
      i += word.length;
      continue;
    }
    const number = at(NUMBER, source, i);
    if (number) { push('number', number); i += number.length; continue; }
    push('plain', source[i]);
    i += 1;
  }
  return tokens;
}

function dockerfile(source: string): Token[] {
  return source.split(/(?<=\n)/).flatMap((line) => {
    const match = DOCKER_INSTRUCTIONS.exec(line);
    if (!match) return scan(line, SHELL);
    return [
      ...(match[1] ? [{ kind: 'plain' as const, text: match[1] }] : []),
      { kind: 'keyword' as const, text: match[2] },
      ...scan(line.slice(match[0].length), SHELL),
    ];
  });
}

function diff(source: string): Token[] {
  return source.split(/(?<=\n)/).map((line) => ({
    kind: line.startsWith('+') ? 'added' : line.startsWith('-') ? 'removed' : 'plain',
    text: line,
  }));
}

export function highlight(source: string, lang: Lang): Token[] {
  switch (lang) {
    case 'python': return scan(source, PYTHON);
    case 'ts': return scan(source, TS);
    case 'dockerfile': return dockerfile(source);
    case 'diff': return diff(source);
    case 'comment': return [{ kind: 'comment', text: source }];
    default: return [{ kind: 'plain', text: source }];
  }
}

/** The monochrome treatment of each token: weight, tone and slant only (P2, P3). */
export const TOKEN_CLASS: Record<TokenKind, string> = {
  plain: '',
  keyword: 'font-semibold text-fg',
  name: 'font-semibold text-fg underline decoration-line-strong underline-offset-[3px]',
  string: 'text-fg-2',
  number: 'text-fg-2',
  comment: 'italic text-fg-3',
  decorator: 'font-semibold text-fg-2',
  constant: 'font-semibold text-fg-2',
  added: 'font-semibold text-fg',
  removed: 'text-fg-3 line-through decoration-fg-3',
};
