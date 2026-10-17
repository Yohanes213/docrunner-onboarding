#!/usr/bin/env python3
"""Turn a DocRunner packet's submitted_fields into the clean answers your app keeps.

    python3 read_answers.py packet.json [--role owner] [--fields fields.json] [--drop-prefix w9_ ...]

packet.json is the body of GET /api/packets/:id (with or without the outer
"packet" key). fields.json (optional) is your allow-list:

    {
      "billing_email":        { "label": "Billing email", "group": "Billing" },
      "po_number":            { "label": "PO number", "group": "Billing" },
      "addon_priority_support": { "label": "Priority support", "group": "Add-ons", "absent": "No" },
      "site_access_notes":    { "label": "Site access notes", "group": "Access", "may_hold_code": true }
    }

Without --fields every signer field of that role is kept (useful to see what
a template sends; use an allow-list in production).

What it does, in order:
  1. Keeps entries whose signer.role is --role.
  2. Drops signatures, initials and signing dates, names starting with a
     sensitive prefix (--drop-prefix, default w9_; repeat it for others such
     as w4_ or bank_), names containing "signature" or ending "_image", and
     null or blank values.
  3. Merges duplicates (a field placed on two pages): the first filled-in
     value wins; for a checkbox, a ticked copy beats an unticked one.
  4. Drops any value that looks like an SSN or EIN, whatever field it's in.
  5. With --fields: keeps only listed names; checkboxes become "Yes", or the
     field's "absent" value when unticked (leave "absent" out to drop
     unticked boxes); a "may_hold_code" field with 3+ digits in a row is
     replaced by a note to read it in DocRunner.

Prints the answers as JSON, in document order. Never prints dropped values.
"""
import argparse
import json
import re
import sys

SKIP_TYPES = {'signature', 'initials', 'signature_date', 'image'}
TAX_ID = re.compile(r'\b(\d{3}-?\d{2}-?\d{4}|\d{2}-?\d{7})\b')
CODE = re.compile(r'\d{3,}')


def entries(packet):
    packet = packet.get('packet', packet)
    fields = packet.get('submitted_fields')
    return fields if isinstance(fields, list) else []


def keep(entry, role, drop_prefixes):
    name = str(entry.get('name') or '')
    signer = entry.get('signer') or {}
    if signer.get('role') != role or not name:
        return False
    if entry.get('type') in SKIP_TYPES or name.startswith(tuple(drop_prefixes)):
        return False
    if 'signature' in name or name.endswith('_image'):
        return False
    value = entry.get('value')
    return value is not None and value != ''


def merge(raw):
    merged = {}
    for entry in raw:
        name, value = entry['name'], entry['value']
        if name not in merged:
            merged[name] = entry
        elif entry.get('type') == 'checkbox' and value is True and merged[name]['value'] is not True:
            merged[name] = entry  # a ticked copy beats an unticked one
    return merged


def answers(packet, role='owner', allow=None, drop_prefixes=('w9_',)):
    merged = merge([e for e in entries(packet) if keep(e, role, drop_prefixes)])
    out = {}
    for order, (name, entry) in enumerate(merged.items()):
        value = entry['value']
        if isinstance(value, str) and TAX_ID.search(value):
            continue  # looks like an SSN or EIN: never kept
        if allow is None:
            out[name] = value
            continue
        spec = allow.get(name)
        if spec is None:
            continue
        if entry.get('type') == 'checkbox' or isinstance(value, bool):
            if value is True:
                value = 'Yes'
            elif 'absent' in spec:
                value = spec['absent']
            else:
                continue
        if spec.get('may_hold_code') and isinstance(value, str) and CODE.search(value):
            value = 'Has numbers that may be a code. Read it in DocRunner.'
        out[name] = {'label': spec.get('label', name), 'group': spec.get('group'), 'value': value, 'order': order}
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('packet')
    parser.add_argument('--role', default='owner')
    parser.add_argument('--fields')
    parser.add_argument('--drop-prefix', action='append', help='field name prefix never kept (default w9_); repeat for more')
    args = parser.parse_args()
    packet = json.load(open(args.packet))
    allow = json.load(open(args.fields)) if args.fields else None
    if not entries(packet):
        print('No submitted_fields on this packet yet: not read yet.', file=sys.stderr)
        sys.exit(1)
    result = answers(packet, args.role, allow, tuple(args.drop_prefix or ['w9_']))
    json.dump(result, sys.stdout, indent=2)
    print(f'\n{len(result)} answers kept for role {args.role}', file=sys.stderr)


if __name__ == '__main__':
    main()
