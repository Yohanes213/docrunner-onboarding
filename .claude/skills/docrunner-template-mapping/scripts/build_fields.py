#!/usr/bin/env python3
"""Build a DocRunner template's field list from measured PDF positions.

Copy this file, replace the SPEC section at the bottom with your document's
blanks, and run:

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


def box(page, name, x, y, who, size=0.015):
    """A box the signer ticks; comes back as true / false."""
    add(page, 'checkbox', name, x, y, size, size * RATIO, who=who)


def sign(page, name, x0, x1, base, who, required=True, h=0.03):
    add(page, 'signature', name, x0 + 0.01, base - h, min(0.25, x1 - x0 - 0.02), h, who=who, required=required)


def signed_on(page, name, x0, x1, base, who, h=0.015):
    # Never required: DocRunner fills the date itself when the person signs,
    # and a required date field blocks the signer's Complete button.
    add(page, 'signature_date', name, x0 + 0.01, base - h, min(0.15, x1 - x0 - 0.02), h, who=who, required=False)


# =====================================================================
# SPEC: an example two-page services agreement. Replace with your own.
# Signer slots: S1, S2 = the customer's signers (the second is optional),
# CO = your company's countersigner.
# =====================================================================

# Page 1: parties, scope, term, price (filled by your app)
var(1, 'company_legal_name', 0.22, 0.60, 0.198)  # a constant your app sends from settings
var(1, 'customer_name', 0.20, 0.91, 0.230)
var(1, 'customer_address', 0.20, 0.91, 0.290)
var(1, 'contract_start_on', 0.30, 0.50, 0.350)
var(1, 'contract_end_on', 0.60, 0.85, 0.350)
var(1, 'monthly_fee', 0.30, 0.45, 0.410)
var(1, 'setup_fee', 0.62, 0.80, 0.410)
choice(1, 'plan_tier', {'basic': 0.30, 'premium': 0.40}, 0.455)  # your app ticks one
area(1, 'scope_of_work', 0.09, 0.93, 0.50, 0.62)

# Page 1: what the customer fills while signing
text(1, 'billing_email', 0.20, 0.50, 0.700, who='S1', required=True)
text(1, 'po_number', 0.55, 0.91, 0.700, who='S1')
box(1, 'accepts_terms_of_service', 0.09, 0.735, who='S1')

# Page 2: signatures (the second customer signer is optional, so not required)
for x0, x1, who, required in [(0.10, 0.40, 'S1', True), (0.52, 0.82, 'S2', False)]:
    sign(2, f'{who.lower()}_signature', x0, x1, 0.40, who, required=required)
    signed_on(2, f'{who.lower()}_date_signed', x0, x1, 0.46, who)
sign(2, 'company_signature', 0.10, 0.40, 0.60, 'CO')
signed_on(2, 'company_date_signed', 0.10, 0.40, 0.66, 'CO')
var(2, 'company_signer_title', 0.10, 0.60, 0.72)

# =====================================================================

json.dump(fields, sys.stdout, indent=1)
print(f'\n{len(fields)} fields: {dict(Counter(f["type"] for f in fields))}, '
      f'by signer: {dict(Counter(f.get("submitter", "app") for f in fields))}', file=sys.stderr)
