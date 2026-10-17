#!/usr/bin/env python3
"""Build a DocRunner template's field list from measured PDF positions.

Generated from the docrunner-template-mapping skill for one PDF in PDFs/.
Run:

    python3 build_fields.py > my_template_fields.json

It prints the JSON list to stdout and a one-line summary to stderr.

Positions are fractions of the page (0 to 1), origin top-left. Page numbers
in the spec are 1-based, the way you read the PDF; the output is 0-based,
the way DocRunner stores them. Field JSON: references/field-schema.md.

Signer slots (who owns a signer field) are free-form labels you map to roles
on the packet template, for example S1 / S2 for a customer's two signers and
CO for your company's countersigner.
"""
import json
import sys
import uuid
from collections import Counter

# Page width / height, so checkboxes come out square. US Letter is 612 x 792.
RATIO = 612 / 792

# When a new version of the PDF moves some pages (a taller logo, a clause
# added), measure how far each page moved and put it here instead of
# re-measuring every field: {page (1-based): offset as a fraction of the page}.
# Positive moves fields down.
SHIFT = {}

fields = []


def add(page, kind, name, x, y, w, h, who=None, required=False, font=10, variant=None):
    y += SHIFT.get(page, 0)
    f = {'uuid': str(uuid.uuid4()), 'type': kind, 'name': name, 'page': page - 1,
         'x': round(x, 4), 'y': round(y, 4), 'w': round(w, 4), 'h': round(h, 4),
         'fontSize': font, 'required': required}
    if variant:
        f['variant'] = variant
    if who:
        f['submitter'] = who
    fields.append(f)


# ---------- Filled by your app (variables) ----------

def var(page, name, x0, x1, base, h=0.015, font=9):
    """An app value on a blank whose underline (or text baseline) is at `base`, from x0 to x1."""
    add(page, 'variable', name, x0 + 0.003, base - h, x1 - x0 - 0.006, h, font=font)


def area(page, name, x0, x1, top, bottom, font=9):
    """A multi-line app value filling an empty box."""
    add(page, 'variable', name, x0, top, x1 - x0, bottom - top, font=font)


def vbox(page, name, x, y, size=0.015):
    """A box the app ticks: send "true" to tick it, "" to leave it empty."""
    add(page, 'variable', name, x, y, size, size * RATIO, variant='checkbox')


def choice(page, field, options, y, size=0.015):
    """One app-ticked box per option, named <field>_<option>. options: {option_key: x}."""
    for key, x in options.items():
        vbox(page, f'{field}_{key}', x, y, size)


# ---------- Filled by a signer ----------

def text(page, name, x0, x1, base, who, required=False, h=0.015, font=9):
    add(page, 'text', name, x0 + 0.003, base - h, x1 - x0 - 0.006, h, who=who, required=required, font=font)


def text_area(page, name, x0, x1, top, bottom, who, font=9):
    add(page, 'text', name, x0, top, x1 - x0, bottom - top, who=who, font=font)


def box(page, name, x, y, who, size=0.015, required=False):
    """A box the signer ticks; comes back as true / false."""
    add(page, 'checkbox', name, x, y, size, size * RATIO, who=who, required=required)


def sign(page, name, x0, x1, base, who, required=True, h=0.03):
    add(page, 'signature', name, x0 + 0.01, base - h, min(0.25, x1 - x0 - 0.02), h, who=who, required=required)


def signed_on(page, name, x0, x1, base, who, h=0.015):
    # Never required: DocRunner fills the date itself when the person signs,
    # and a required date field blocks the signer's Complete button.
    add(page, 'signature_date', name, x0 + 0.01, base - h, min(0.15, x1 - x0 - 0.02), h, who=who, required=False)


# =====================================================================
# SPEC: 03_ip_assignment.pdf (1 page). Signers: S1 = Owner (client, signs
# first), CO = PM (Northbeam Studio, countersigns, signing order 2).
# =====================================================================

# Page 1: filled by your app
var(1, 'project_name', 0.209, 0.902, 0.1111)
var(1, 'client_company_name', 0.225, 0.902, 0.1414)

# Page 1: the Owner ticks these while signing
box(1, 'confirms_materials_owned', 0.098, 0.3725, 'S1', required=True)
box(1, 'portfolio_permission', 0.098, 0.3952, 'S1')  # optional

# Page 1: signature blocks (Owner left, PM right). Dates are never required.
sign(1, 'owner_signature', 0.098, 0.458, 0.4937, 'S1')
text(1, 'owner_printed_name', 0.098, 0.458, 0.5417, 'S1')
text(1, 'owner_title', 0.098, 0.458, 0.5896, 'S1')
signed_on(1, 'owner_date_signed', 0.098, 0.458, 0.6376, 'S1')

sign(1, 'pm_signature', 0.524, 0.884, 0.4937, 'CO')
text(1, 'pm_printed_name', 0.524, 0.884, 0.5417, 'CO')
text(1, 'pm_title', 0.524, 0.884, 0.5896, 'CO')
signed_on(1, 'pm_date_signed', 0.524, 0.884, 0.6376, 'CO')


json.dump(fields, sys.stdout, indent=1)
print(f'\n{len(fields)} fields: {dict(Counter(f["type"] for f in fields))}, '
      f'by signer: {dict(Counter(f.get("submitter", "app") for f in fields))}', file=sys.stderr)
