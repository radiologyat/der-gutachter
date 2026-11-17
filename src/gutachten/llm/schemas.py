# SPDX-License-Identifier: AGPL-3.0-or-later
"""JSON schemas for constrained LLM extraction (Phase 2+).

Field names mirror the DB tables so results persist without a mapping layer.
Enum values are German domain terms — they land verbatim in the Aktenauszug.
"""

DOC_CLASSIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "enum": None},
        "title": {"type": "string"},
        "doc_date": {"type": ["string", "null"], "description": "ISO-8601"},
        "author": {"type": ["string", "null"]},
        "institution": {"type": ["string", "null"]},
        "patient_name": {"type": ["string", "null"]},
        "patient_dob": {"type": ["string", "null"]},
    },
    "required": ["doc_type", "title"],
    "additionalProperties": False,
}

DOC_TYPES = [
    "arztbrief", "notfallbericht", "austrittsbericht", "op_bericht", "radiologie",
    "labor", "rezept", "gutachten", "gericht", "versicherung", "korrespondenz",
    "formular", "sonstiges",
]

_NULLABLE_STR = {"type": ["string", "null"]}

# One call per page: does a new document start here, and if so, what is it?
PAGE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "starts_new_document": {"type": "boolean"},
        "doc_type": {"type": "string", "enum": DOC_TYPES},
        "title": {"type": "string"},
        "doc_date": {**_NULLABLE_STR, "description": "ISO-8601, nur wenn im Text"},
        "author": _NULLABLE_STR,
        "institution": _NULLABLE_STR,
        "patient_name": _NULLABLE_STR,
        "patient_dob": _NULLABLE_STR,
    },
    "required": [
        "starts_new_document", "doc_type", "title", "doc_date", "author",
        "institution", "patient_name", "patient_dob",
    ],
    "additionalProperties": False,
}

_QUOTED_VALUE = {
    "anyOf": [
        {"type": "null"},
        {
            "type": "object",
            "properties": {"value": {"type": "string"}, "quote": {"type": "string"}},
            "required": ["value", "quote"],
            "additionalProperties": False,
        },
    ]
}

# Deckblatt / Gutachtenauftrag: case metadata, deadlines, Beweisfragen.
COVER_SCHEMA = {
    "type": "object",
    "properties": {
        "auftraggeber": _QUOTED_VALUE,
        "aktenzeichen": _QUOTED_VALUE,
        "patient_name": _QUOTED_VALUE,
        "patient_dob": _QUOTED_VALUE,
        "accident_date": _QUOTED_VALUE,
        "deadlines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["frist", "begutachtung", "termin"]},
                    "date": {"type": "string"},
                    "label": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["kind", "date", "label", "quote"],
                "additionalProperties": False,
            },
        },
        "questions": {
            "type": "array",
            "items": {"type": "string", "description": "Beweisfrage wörtlich"},
        },
    },
    "required": [
        "auftraggeber", "aktenzeichen", "patient_name", "patient_dob",
        "accident_date", "deadlines", "questions",
    ],
    "additionalProperties": False,
}

DOC_CLASSIFICATION_SCHEMA["properties"]["doc_type"]["enum"] = DOC_TYPES

FACT_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact_date": {"type": ["string", "null"]},
                    "fact_date_end": {
                        "type": ["string", "null"],
                        "description": "Ende eines Zeitraums (Hospitalisation, Reha, AUF)",
                    },
                    "page": {
                        "type": ["integer", "null"],
                        "description": "Blattzahl (Bl. N) der Fundstelle",
                    },
                    "event_category": {
                        "type": "string",
                        "enum": [
                            "vorbefund", "trauma", "diagnostik", "op",
                            "konservativ", "reha", "arbeitsfaehigkeit",
                            "begutachtung", "korrespondenz",
                        ],
                    },
                    "causality": {
                        "type": "string",
                        "enum": [
                            "vorschaden", "unfallkausal", "kombiniert",
                            "unklar", "none",
                        ],
                        "description": "relation to the indexed accident",
                    },
                    "body_region": {"type": ["string", "null"]},
                    "laterality": {
                        "type": "string",
                        "enum": ["links", "rechts", "beidseits", "na"],
                    },
                    "icd10": {"type": ["string", "null"]},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "quote": {
                        "type": "string",
                        "description": "verbatim passage from the source page",
                    },
                },
                "required": [
                    "fact_date", "fact_date_end", "page", "event_category", "causality",
                    "laterality", "title", "summary", "quote",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["facts"],
    "additionalProperties": False,
}


NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 400},
                    "refs": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                },
                "required": ["text", "refs"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}

BASIS_SCHEMA = {
    "type": "object",
    "properties": {
        "points": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "group": {"type": "string",
                              "enum": ["fuer_unfall", "fuer_vorzustand", "offen"]},
                    "text": {"type": "string", "maxLength": 300},
                    "refs": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                },
                "required": ["group", "text", "refs"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["points"],
    "additionalProperties": False,
}
