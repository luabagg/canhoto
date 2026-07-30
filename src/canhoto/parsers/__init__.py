"""User/plugin statement parser port (Protocol, loader, registry helpers).

No built-in bank parsers ship in this package. Implementations live under the
user data dir and are loaded only when listed/enabled in config.
"""

from canhoto.parsers.loader import (
    ParserLoadError,
    ParserNotFoundError,
    choose_parser,
    load_enabled_parsers,
    load_parser_by_id,
)
from canhoto.parsers.protocol import StatementParser
from canhoto.parsers.scaffold import (
    class_name_for,
    module_filename,
    render_stub,
    validate_parser_id,
    write_stub_module,
)

__all__ = [
    "ParserLoadError",
    "ParserNotFoundError",
    "StatementParser",
    "choose_parser",
    "class_name_for",
    "load_enabled_parsers",
    "load_parser_by_id",
    "module_filename",
    "render_stub",
    "validate_parser_id",
    "write_stub_module",
]
