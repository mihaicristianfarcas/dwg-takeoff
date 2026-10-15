"""JSON schema of the takeoff plan every AI backend must return (strict structured output)."""

SOURCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["layer", "kinds", "pattern", "color", "block", "table_object", "handles"],
    "properties": {
        "layer": {"type": ["string", "null"], "description": "Exact layer name (null only for table_polygon sources)."},
        "kinds": {
            "type": "array",
            "items": {"type": "string", "enum": ["hatch", "solid", "closed", "line", "block", "text", "table_polygon"]},
        },
        "pattern": {"type": ["string", "null"], "description": "Hatch pattern filter, e.g. SOLID, AR-B88; null = any."},
        "color": {
            "type": ["string", "null"],
            "description": 'Effective colour filter "#rrggbb" as listed in the digest; null = any.',
        },
        "block": {"type": ["string", "null"], "description": "Block name filter for kind=block; null = any."},
        "table_object": {
            "type": ["string", "null"],
            "description": "Object name from an embedded setting-out table (for table_polygon).",
        },
        "handles": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": "Restrict to these entity handles; null = all matching entities.",
        },
    },
}

PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["language", "summary", "items", "general_notes", "questions_for_user"],
    "properties": {
        "language": {"type": "string"},
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "label",
                    "request_text",
                    "unit",
                    "status",
                    "confidence",
                    "reasoning",
                    "components",
                    "assumptions",
                    "questions",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "request_text": {"type": "string"},
                    "unit": {"type": "string", "enum": ["m²", "m", "m³", "buc"]},
                    "status": {"type": "string", "enum": ["measured", "assumption_based", "not_in_drawing"]},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "reasoning": {"type": "string"},
                    "components": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "label",
                                "measure",
                                "entries",
                                "subtract_entries",
                                "sources",
                                "subtract_sources",
                                "region",
                                "tolerance_m",
                                "factors",
                            ],
                            "properties": {
                                "label": {"type": "string"},
                                "entries": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Catalogue entry ids to measure (S3, L12, B2, O2.4 ...).",
                                },
                                "subtract_entries": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Catalogue entry ids removed from what is measured.",
                                },
                                "measure": {
                                    "type": "string",
                                    "enum": [
                                        "area",
                                        "length",
                                        "perimeter",
                                        "count",
                                        "strip_area",
                                        "enclosed_area",
                                        "count_groups",
                                    ],
                                },
                                "sources": {
                                    "type": "array",
                                    "items": SOURCE_SCHEMA,
                                    "description": "Raw filters, only when no catalogue entry fits; else [].",
                                },
                                "subtract_sources": {"type": "array", "items": SOURCE_SCHEMA},
                                "region": {"type": ["string", "null"], "enum": ["site", None]},
                                "tolerance_m": {"type": ["number", "null"]},
                                "factors": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["name", "value", "unit", "origin", "note"],
                                        "properties": {
                                            "name": {"type": "string"},
                                            "value": {"type": "number"},
                                            "unit": {"type": "string", "enum": ["m", "m²", "-"]},
                                            "origin": {"type": "string", "enum": ["drawing", "document", "assumed"]},
                                            "note": {"type": "string"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "assumptions": {"type": "array", "items": {"type": "string"}},
                    "questions": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "general_notes": {"type": "array", "items": {"type": "string"}},
        "questions_for_user": {"type": "array", "items": {"type": "string"}},
    },
}
