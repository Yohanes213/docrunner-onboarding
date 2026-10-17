#!/usr/bin/env python3
"""Find the fillable spots in a PDF so Claude can place DocRunner fields without hand measuring.

    pip install pdfplumber
    python3 find_blanks.py contract.pdf > blanks.json          # every page
    python3 find_blanks.py contract.pdf --pages 1-3,10          # some pages

Prints a JSON list to stdout and a readable table to stderr. Each candidate:

    { "page": 1, "kind": "line", "x0": 0.200, "x1": 0.910, "base": 0.2901,
      "left": "Customer address:", "right": "", "above": "", "below": "", "hint": "" }
    { "page": 3, "kind": "box", "x": 0.212, "y": 0.2505, "size": 0.019,
      "left": "", "right": "Premium plan", "above": "", "below": "", "hint": "" }

Kinds:
  line   an underline or a run of underscores: a text blank. x0/x1 are its
         ends, base is the line's height on the page (the field sits above it).
  box    a small square (drawn box or a box glyph like the "empty box" character):
         a checkbox. x/y is its top-left corner, size its width.

Coordinates are fractions of the page (0 to 1), origin top-left, pages
1-based, matching build_fields.py's helpers: var()/text() take x0, x1, base;
vbox()/box() take x, y.

"left", "right", "above" and "below" are the nearest words, so you can tell
what each blank is for (many forms print the label under the line). "hint"
says signature or date when the words beside or under it say so.

It finds what's drawn. Check its list against the rendered pages: it can
miss blanks that are just white space (no line, no underscores), and it
lists table rules and decorative lines that aren't blanks. Lines that span
almost the whole page width are left out unless you pass --keep-rules.
"""
import argparse
import json
import re
import sys

try:
    import pdfplumber
except ImportError:
    sys.exit('Needs pdfplumber: pip install pdfplumber')

BOX_GLYPHS = set('☐□❑❒◻▢■☑☒')
UNDERSCORES = re.compile(r'_{3,}')


def page_numbers(spec, count):
    if not spec:
        return list(range(1, count + 1))
    out = []
    for part in spec.split(','):
        a, _, b = part.partition('-')
        out.extend(range(int(a), int(b or a) + 1))
    return [n for n in out if 1 <= n <= count]


def near_words(words, x0, x1, top, bottom):
    """The words just left of, right of, above and below a spot (PDF points)."""
    mid = (top + bottom) / 2
    row = [w for w in words if w['top'] - 3 <= mid <= w['bottom'] + 3]
    left = [w for w in row if w['x1'] <= x0 + 1 and x0 - w['x1'] < 160]
    right = [w for w in row if w['x0'] >= x1 - 1 and w['x0'] - x1 < 160]
    above = [w for w in words if bottom - 30 < w['bottom'] < top - 1 and w['x1'] > x0 - 10 and w['x0'] < x1 + 10]
    below = [w for w in words if bottom + 1 < w['top'] < bottom + 14 and w['x1'] > x0 - 10 and w['x0'] < x1 + 10]
    text = lambda ws: ' '.join(w['text'] for w in sorted(ws, key=lambda w: w['x0'])).strip()
    return text(left[-6:]), text(right[:6]), text(above[-8:]), text(below[:8])


def hint_for(*texts):
    t = ' '.join(texts).lower()
    if 'signature' in t or re.search(r'\bsign(ed)?\b', t):
        return 'signature'
    if re.search(r'\bdate\b', t):
        return 'date'
    return ''


def scan(pdf_path, pages_spec=None, keep_rules=False):
    found = []
    with pdfplumber.open(pdf_path) as pdf:
        for n in page_numbers(pages_spec, len(pdf.pages)):
            page = pdf.pages[n - 1]
            W, H = float(page.width), float(page.height)
            words = [w for w in page.extract_words(keep_blank_chars=False) if not UNDERSCORES.fullmatch(w['text'])]
            lines = []

            # Drawn lines and hairline rectangles (many PDFs draw underlines as thin rects).
            for obj in page.lines + page.rects:
                x0, x1, top, bottom = obj['x0'], obj['x1'], obj['top'], obj['bottom']
                if bottom - top <= 2.5 and x1 - x0 >= 18:
                    if not keep_rules and (x1 - x0) > 0.85 * W:
                        continue
                    lines.append((x0, x1, (top + bottom) / 2))

            # Runs of underscores in the text.
            for w in page.extract_words(keep_blank_chars=True):
                for m in UNDERSCORES.finditer(w['text']):
                    chars_w = (w['x1'] - w['x0']) / max(len(w['text']), 1)
                    x0 = w['x0'] + m.start() * chars_w
                    x1 = w['x0'] + m.end() * chars_w
                    lines.append((x0, x1, w['bottom']))

            # Merge lines that overlap on the same height (a rect and underscores drawn together).
            lines.sort(key=lambda l: (round(l[2]), l[0]))
            merged = []
            for x0, x1, base in lines:
                if merged and abs(merged[-1][2] - base) < 2.5 and x0 <= merged[-1][1] + 2:
                    px0, px1, pbase = merged[-1]
                    merged[-1] = (min(px0, x0), max(px1, x1), max(pbase, base))
                else:
                    merged.append((x0, x1, base))
            for x0, x1, base in merged:
                left, right, above, below = near_words(words, x0, x1, base - 10, base)
                found.append({'page': n, 'kind': 'line', 'x0': round(x0 / W, 4), 'x1': round(x1 / W, 4),
                              'base': round(base / H, 4), 'left': left, 'right': right, 'above': above, 'below': below,
                              'hint': hint_for(left, right, below)})

            # Checkboxes: small squares, drawn or as a glyph.
            boxes = []
            for r in page.rects:
                w_, h_ = r['x1'] - r['x0'], r['bottom'] - r['top']
                if 5 <= w_ <= 16 and 5 <= h_ <= 16 and abs(w_ - h_) <= 2.5:
                    boxes.append((r['x0'], r['top'], w_))
            for c in page.chars:
                if c['text'] in BOX_GLYPHS:
                    boxes.append((c['x0'], c['top'], c['x1'] - c['x0']))
            seen = set()
            for x, y, s in sorted(boxes, key=lambda b: (round(b[1]), b[0])):
                key = (round(x), round(y))
                if key in seen:
                    continue
                seen.add(key)
                left, right, above, below = near_words(words, x, x + s, y, y + s)
                found.append({'page': n, 'kind': 'box', 'x': round(x / W, 4), 'y': round(y / H, 4),
                              'size': round(s / W, 4), 'left': left, 'right': right, 'above': above, 'below': below, 'hint': ''})
    return found


def main():
    parser = argparse.ArgumentParser(description='Find fillable spots in a PDF for DocRunner fields.')
    parser.add_argument('pdf')
    parser.add_argument('--pages', help='e.g. 1-3,10 (1-based)')
    parser.add_argument('--keep-rules', action='store_true', help='also list lines spanning nearly the whole page')
    args = parser.parse_args()
    found = scan(args.pdf, args.pages, args.keep_rules)
    json.dump(found, sys.stdout, indent=1)
    for f in found:
        where = f"x {f['x0']:.3f}-{f['x1']:.3f} base {f['base']:.4f}" if f['kind'] == 'line' else f"x {f['x']:.3f} y {f['y']:.4f}"
        print(f"p{f['page']:<3} {f['kind']:<4} {where:<32} {f['hint']:<9} {f['left'][-30:]!r} | {f['right'][:24]!r} | below {f['below'][:30]!r}", file=sys.stderr)
    print(f"{len(found)} candidates: {sum(f['kind'] == 'line' for f in found)} lines, {sum(f['kind'] == 'box' for f in found)} boxes", file=sys.stderr)


if __name__ == '__main__':
    main()
