#!/bin/sh
# Pack plan.html into one portable file, then inline the prototype scripts.
# pack.mjs inlines only the html-plan runtime, so the prototype (proto-lab.js)
# and its company logos (proto-logos.js) go in here.
set -e
cd "$(dirname "$0")"
ROOT="$(git rev-parse --show-toplevel)"
node "$HOME/.claude/plugins/cache/claude-community/html-plan/1.0.0/skills/html-plan/runtime/pack.mjs" plan.html --root "$ROOT" "$@"
python3 - <<'PY'
p = 'plan.packed.html'
s = open(p).read()
for name in ('proto-logos.js', 'proto-lab.js'):
    js = open(name).read()
    assert '</script' not in js, name
    tag = '<script src="%s"></script>' % name
    assert s.count(tag) == 1, tag
    s = s.replace(tag, '<script>\n' + js + '\n</script>')
open(p, 'w').write(s)
print('inlined proto-logos.js and proto-lab.js into', p)
PY
