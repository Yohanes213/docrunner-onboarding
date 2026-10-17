#!/usr/bin/env python3
"""Check a DocRunner packet template is ready for your app to create packets from it.

    export DOCRUNNER_API_KEY=...            # Settings > Developer Tools > API Keys
    python3 check_packet_template.py 42 [--sends variables.txt] [--roles owner,pm]

Reads GET /api/packet_templates/:id (read only, changes nothing) and prints:
  - name, test mode on or off, archived or not
  - each signer role: its key, how many signers, signing order, and whether
    the API accepts the key (only owner, tenant and pm are accepted)
  - every variable the documents expect, with checkbox variables marked
  - with --sends: the variables your app sends that the template doesn't have
    (those values would be dropped) and the template variables your app
    doesn't send (those blanks would print empty). One name per line in the
    file; names are normalized the way DocRunner saves them.
  - with --roles: role keys your app sends that the template doesn't have, and
    template roles your app doesn't send (a packet missing a role never completes)

Exits 1 when something would break packets, so it can run in CI.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = os.environ.get('DOCRUNNER_API_URL', 'https://app.docrunner.io/api').rstrip('/')
ACCEPTED_ROLE_KEYS = {'owner', 'tenant', 'pm'}


def variable_name(name):
    """How DocRunner saves a variable name: snake_case, repeated underscores collapsed."""
    s = str(name).strip().replace('#', '_num_')
    s = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', s).lower()
    s = re.sub(r'[^a-z0-9]+', '_', s)
    return re.sub(r'_+', '_', s).strip('_')


def fetch(template_id, key):
    req = urllib.request.Request(f'{API}/packet_templates/{int(template_id)}', headers={'X-API-Key': key, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)['packet_template']
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf8', 'replace')
        sys.exit({401: 'DocRunner did not accept the key.', 404: f'Packet template {template_id} not found in this account.'}.get(e.code, f'DocRunner answered {e.code}: {body[:200]}'))


def main():
    parser = argparse.ArgumentParser(description='Check a DocRunner packet template is ready for the API.')
    parser.add_argument('id', type=int)
    parser.add_argument('--sends', help='file with the variable names your app sends, one per line')
    parser.add_argument('--roles', help='comma-separated role keys your app sends, e.g. owner,pm')
    args = parser.parse_args()
    key = os.environ.get('DOCRUNNER_API_KEY') or sys.exit('Set DOCRUNNER_API_KEY first.')

    t = fetch(args.id, key)
    problems, notes = [], []
    print(f"{t['name']} (packet template {t['id']})")
    print(f"  Test mode: {'ON (no emails; signing links come back from send)' if t.get('test_mode') else 'off (signers get real emails)'}")
    if t.get('archived_at'):
        problems.append('archived: packets cannot be created from it')

    roles = t.get('recipient_roles') or []
    print('  Signer roles:')
    for r in sorted(roles, key=lambda r: (r.get('signing_order') or 0, r.get('key') or '')):
        ok = r.get('key') in ACCEPTED_ROLE_KEYS
        print(f"    {r.get('key'):<10} \"{r.get('name')}\"  up to {r.get('max_count')} signer(s), step {r.get('signing_order')}  {'ok' if ok else 'NOT ACCEPTED by the API'}")
        if not ok:
            problems.append(f"role key {r.get('key')!r} is not accepted by the API: rename the document template's signer to Owner, Tenant or PM")
    if not roles:
        problems.append('no signer roles: add signers to the document templates (Edit fields)')

    variables = t.get('available_variables') or []
    names = sorted({v['name'] for v in variables})
    print(f'  Variables ({len(names)}):')
    for v in sorted(variables, key=lambda v: (v.get('template_name') or '', v['name'])):
        print(f"    {v['name']:<36} {'checkbox' if v.get('variant') == 'checkbox' else '':<9} {v.get('template_name') or ''}")

    if args.sends:
        sends = {variable_name(line) for line in open(args.sends) if line.strip()}
        dropped = sorted(sends - set(names))
        empty = sorted(set(names) - sends)
        if dropped:
            problems.append(f'your app sends variables the template does not have (dropped): {", ".join(dropped)}')
        if empty:
            notes.append(f'template variables your app does not send (print empty): {", ".join(empty)}')

    if args.roles:
        mine = {r.strip() for r in args.roles.split(',') if r.strip()}
        theirs = {r.get('key') for r in roles}
        if mine - theirs:
            problems.append(f'your app sends role keys the template does not have: {", ".join(sorted(mine - theirs))}')
        if theirs - mine:
            problems.append(f'template roles your app does not send (packets would never complete): {", ".join(sorted(theirs - mine))}')

    for n in notes:
        print(f'  Note: {n}')
    for p in problems:
        print(f'  PROBLEM: {p}')
    print('  Ready for the API.' if not problems else f'  {len(problems)} problem(s).')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
