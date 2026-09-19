import json
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

@lru_cache(None)
def validator(name):
    schema = json.loads(Path(__file__).with_name('contracts.schema.json').read_text())
    if name not in schema["$defs"]:
        raise ValueError(f"Unknown contract {name}")
    schema["$ref"] = "#/$defs/" + name
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())

def validate(name, value):
    validator(name).validate(value)
    return value
