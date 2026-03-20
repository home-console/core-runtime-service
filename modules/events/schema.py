from typing import Any


def validate_schema(schema: dict[str, Any], data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValueError(f"Invalid payload: expected dict, got {type(data).__name__}")

    errors = []

    for field, rule in schema.items():
        is_optional = False

        # optional field
        if isinstance(rule, tuple) and rule[0] == "optional":
            is_optional = True
            rule = rule[1]

        if field not in data:
            if not is_optional:
                errors.append(f"Missing required field: {field}")
            continue

        value = data[field]

        # type check
        if isinstance(rule, type):
            if not isinstance(value, rule):
                errors.append(f"Invalid type for '{field}': expected {rule.__name__}")

        # enum
        elif isinstance(rule, tuple):
            if value not in rule:
                errors.append(f"Invalid value for '{field}': {value}")

    if errors:
        raise ValueError(", ".join(errors))
