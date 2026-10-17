# DocRunner template field JSON

A DocRunner document template stores its fields as one JSON list, plus a
list of its signers. `scripts/build_fields.py` writes fields with a signer
**label** (`submitter: "S1"`); `scripts/make_loader.py` turns each label into
the template signer's id (`submitter_uuid`) when it places them.

```json
{
  "uuid": "eea72051-de69-498e-8979-4acc4d0aa700",
  "type": "variable",
  "name": "customer_name",
  "page": 0,
  "x": 0.203,
  "y": 0.2864,
  "w": 0.704,
  "h": 0.015,
  "fontSize": 9,
  "required": false,
  "submitter": "S1",
  "variant": "checkbox"
}
```

| Key | Meaning |
|---|---|
| `uuid` | Unique id per field. Generate a new one per field. |
| `type` | See the types below. |
| `name` | The field's name. For `variable` fields it's the key your app sends; for signer fields it's the `name` that comes back in `submitted_fields`. snake_case. |
| `page` | 0-based page index. |
| `x`, `y`, `w`, `h` | Position and size as fractions of the page, origin top-left. |
| `fontSize` | Text size in points. 9 or 10 fits most form blanks. |
| `required` | Whether the signer must fill it before completing. Leave `false` for variables and for `signature_date`. |
| `submitter` | In the generated file: the signer label that owns the field (signer fields only; omit for `variable`). |
| `submitter_uuid` | In DocRunner: the id of the template signer that owns the field. `make_loader.py` fills it from `submitter`. |
| `variant` | `"checkbox"` on a `variable` field draws a box that ticks when the value is `"true"`. |

## Types

| Type | Filled by | Comes back as |
|---|---|---|
| `variable` | Your app, from `variables` on create | (echoed in the packet's `variables`) |
| `text` | A signer | string, or `null` if empty |
| `checkbox` | A signer | `true` / `false` |
| `date` | A signer | string |
| `radio`, `dropdown` | A signer | the chosen option |
| `signature` | A signer | the signer's typed name |
| `initials` | A signer | the typed initials |
| `signature_date` | DocRunner, when that signer signs | the date |

DocRunner's editor also has `file`, `payment`, `people` and `status`
fields; this packet doesn't cover them.

## Signers in the field list vs. roles on the packet

In the field list, `submitter` names a signer slot (for example `S1` and
`S2` for two customers, `CO` for your company's countersigner). On the
packet template those slots map to roles. When your app creates a packet it
sends signers by **role key**. The API accepts three keys, `owner`,
`tenant` and `pm`, which you use as generic slots whatever your signers are
called (for example customers = `owner`, countersigner = `pm`). Signers
under one key fill that role's slots in order: the first fills S1, the
second S2.

## The template's signers

Stored next to the fields:

```json
[{ "uuid": "4871fd41-...", "name": "Owner 1", "signing_order": 1 },
 { "uuid": "35d6d27b-...", "name": "Owner 2", "signing_order": 1 },
 { "uuid": "8fe59695-...", "name": "PM", "signing_order": 2 }]
```

Signers with the same `signing_order` sign at the same time; higher numbers
sign after. The packet template's roles come from these names: a trailing
number is dropped and the rest lowercased ("Owner 1", "Owner 2" become one
role `owner` with up to two signers; "PM" becomes `pm`).
