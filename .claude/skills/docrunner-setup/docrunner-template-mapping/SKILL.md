---
name: docrunner-template-mapping
description: Turn any PDF (contract, service agreement, offer letter, consent or intake form, vendor or onboarding paperwork) into a working DocRunner template end to end - find every blank in the PDF automatically, decide which the app fills as variables and which each signer fills, name variables so values actually land, handle checkboxes the app ticks, generate the field list, and place the fields in the template (with a backup) instead of dragging hundreds of fields by hand. Use this whenever someone is setting up or revising a DocRunner template, mapping fields or merge variables, laying out signature blocks, or a new version of a PDF arrives and the fields need to move, even if they don't say "skill" or "mapping".
---

# DocRunner template mapping

Turn a PDF into a DocRunner template your app can fill and your signers can
complete, with Claude doing the placing. Along the way you get a **field
map** (every blank, who fills it, its name), a **field list** (the JSON
DocRunner stores: type, name, page, position, signer), and the fields placed
in the template.

## 1. Build the field map first

Go through the PDF page by page and list every blank. For each, decide who
fills it:

| Who fills it | DocRunner field | Examples |
|---|---|---|
| **Your app**, before anyone sees it | `variable` | Customer name, start date, price, plan, account number, the record's id |
| **Your app, same on every packet** | `variable` | Your company's legal name, address, phone. Send them from settings, not baked into the PDF, so a change is one edit. |
| **A signer**, while signing | `text`, `checkbox`, `date`, `radio`, `dropdown` | Billing contact, PO number, emergency contact, "I agree" boxes, preferences |
| **A signer's signature** | `signature`, `initials`, `signature_date` | One per signer per signing spot |

Write the map as a table (page, blank, who fills, field name). It's the
document you review with whoever owns the paperwork before placing
anything, and it saves a second round of placement.

Questions to settle while mapping:
- Which values come from your app's data, and which does the signer type?
- Which blanks are constants (your company's details)?
- How many signers, and in what order? (For example one or two customers
  sign first, then your company countersigns.)
- Which fields must the signer fill (`required`)? Keep this short: every
  required field is a way for a signer to get stuck.
- Is any page optional (a state-specific disclosure, an add-on's terms)?
  The API can't drop a document per packet yet, so plan a second packet
  template for that case.

## 2. Name things so values land

- **Variable names are snake_case, and DocRunner normalizes them on save**:
  repeated underscores collapse (`plan__tier` is stored as `plan_tier`).
  Name variables in normalized form from the start, and normalize keys in
  your app before sending (see `docrunner-packets-api`).
- **Name variables after your app's own field keys** wherever you can
  (`customer_name`, `contract_start_on`). The map then doubles as the
  integration spec, and computed values stand out (mark them *computed*).
- **Signer field names** come back to your app as `submitted_fields[].name`.
  Name them for what your app will do with them (`billing_email`,
  `po_number`), not for their position on the page.
- **A field placed twice** (the same phone number on two pages) comes back
  twice. Give it the same name on purpose only if your app merges
  duplicates.

## 3. Checkboxes your app ticks

For a choice your app makes (a plan tier, yes / no, include / exclude, or a
multi-select of add-ons), put **one `variable` field with
`variant: "checkbox"` over each box**, named `<field>_<option>`:

```
plan_tier_basic       over the "Basic" box
plan_tier_premium     over the "Premium" box
```

Your app sends `"true"` for the chosen option and `""` for the others. The
box ticks only on the literal string `"true"`. For a multi-select, send
`"true"` for each chosen option.

Checkboxes a **signer** ticks are ordinary `checkbox` fields owned by that
signer; their value comes back as `true` / `false`.

## 4. Signature blocks

- One `signature` field per signer per signing spot, and usually a
  `signature_date` beside it.
- **Never make a `signature_date` required.** DocRunner fills the date in
  itself when the person signs; a required date field blocks the signer's
  Complete button.
- A signer who may not exist on every packet (an optional second customer,
  a co-applicant) gets fields that aren't required, so a packet without them
  can still complete.
- Give signature fields readable names that say who and where
  (`signer_1_signature_terms`), since they appear in `submitted_fields`
  with the signer's typed name as the value.

## 5. Find the blanks and build the field list

Don't measure by hand. Two scripts do it (Python 3; `find_blanks.py` also
needs `pip install pdfplumber`):

**a. Find the blanks.**

```
python3 scripts/find_blanks.py contract.pdf > blanks.json
```

It lists every underline, run of underscores, small box and box glyph on
each page, with exact positions as fractions of the page and the words to
its left, right, above and below (many forms print the label under the
line: "Signature", "Date", "Street Address"). It marks likely signature and
date lines. See the docstring for the output shape.

**b. Look at the pages.** Render them (`pdftoppm -r 80 -png contract.pdf
page`) and look at each one next to its candidates:
- Blanks that are just white space in the text (no line, no underscores)
  aren't found. Measure those from the image: position in pixels divided by
  the image's width or height.
- Table rules and decorative lines show up as candidates. Leave them out.
- Lines spanning almost the whole page are skipped unless you pass
  `--keep-rules`.

**c. Write the spec.** Copy `scripts/build_fields.py` and replace the example
at the bottom. Each candidate becomes one helper call, using the field map
from step 1 to decide who fills it:

| Candidate | App fills it | A signer fills it |
|---|---|---|
| `line` (x0, x1, base) | `var(page, name, x0, x1, base)` | `text(page, name, x0, x1, base, who)`, or `sign(...)` / `signed_on(...)` for signature and date lines |
| `box` (x, y) | `vbox(page, name, x, y)` | `box(page, name, x, y, who)` |
| an empty area | `area(page, name, x0, x1, top, bottom)` | `text_area(...)` |

`who` is a signer label you choose (`S1`, `S2`, `CO`). You map labels to the
template's signers in step 6.

```
python3 my_build_fields.py > my_template_fields.json
```

DocRunner prints a variable's text at the top of its field box, so the
helpers put the box just above the line, with its bottom edge on the line.
Keep boxes about one line of text tall (the default) or the text floats
above the line.

Positions are fractions of the page, origin top-left; pages are 1-based in
the spec and 0-based in the output. Checkboxes stay square because height
is scaled by the page's width/height ratio (`612/792` for US Letter;
change `RATIO` for A4).

**When the PDF changes** (a new logo, a clause added), run `find_blanks.py`
on the new version and compare, or measure how far each affected page
moved and put it in `SHIFT = {page: offset}`; every field on that page
moves with it.

Field JSON shape and every type: `references/field-schema.md`.

## 6. Place the fields in DocRunner

There's no published API for writing a template's fields. The template
editor saves all of a template's fields in one request, so the loader sends
the same request, in your own signed-in browser, on your own account.

**a. Choose the signer names.** The names on the template's signers decide
the role keys the API uses: DocRunner drops a trailing number and lowercases
the rest, so "Owner 1" and "Owner 2" become role `owner` and "PM" becomes
`pm`. If your app creates packets through the API, name them "Owner",
"Owner 1", "Owner 2", "Tenant", "Tenant 1" or "PM": those are the only keys
the API accepts (see `docrunner-packets-api`).

**b. Make the loader.** It checks every field first (types, positions on the
page, a signer on every signer field, no required `signature_date`) and
writes nothing if anything is wrong:

```
python3 scripts/make_loader.py my_template_fields.json \
    --slot S1="Owner 1" --slot S2="Owner 2" --slot CO="PM:2" > place_fields.js
```

`--slot LABEL="Signer name:order"` maps each label to a signer on the
template (the number after the colon is the signing order; the default is
1). Add `--dry-run` to see what it would save without saving. Add `--append`
to add fields to a template that already has some, instead of replacing
them.

**c. Run it on the template's field editor page.** In DocRunner, open the
template and press Edit fields (the page at `/templates/<id>/fields`). Then:
- **With a browser tool** (Claude in Chrome, or Playwright connected to the
  developer's signed-in browser), run the contents of `place_fields.js` in
  that page.
- **By hand:** open the browser's DevTools console on that page, paste the
  contents of `place_fields.js`, and press Enter.

The loader downloads a backup of the template's current fields and signers
(`docrunner-template-<id>-backup.json`) before it changes anything. It
matches your signer names to the template's signers, adds the missing ones,
removes signers no field uses (a new template starts with a default
"Signer", which would otherwise become an extra role and stop packets from
completing), saves, and reloads the editor. DocRunner refuses a save that would
leave the template with no signing fields.

To undo, make a loader from the backup's `fields` (they already carry
`submitter_uuid`, so no `--slot` is needed for fields that have it) or put
the fields back in the editor.

**d. Check it.**
1. Look through every page in the editor. Fix anything that's off right
   there in the editor, or fix the spec and run the loader again.
2. Create a **test packet** from your app with a recognizable value in every
   variable (for example `T-customer_name`) and every signer set to your own
   email (`docrunner-packets-api`, test mode).
3. Sign it as each signer, typing `T-<field name>` into every signer field.
4. Read it back (`GET /api/packets/:id`) and check every name you expect is
   in `submitted_fields` with your test value. Anything missing is a typo or
   a field on the wrong signer.

Keep that test packet's response as a fixture for your app's tests.
