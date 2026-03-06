# Tool modules for the MCP server.
#
# Each *.py file here (except __init__.py and files starting with _) is
# automatically imported by the server on startup.
#
# A module is only loaded if it defines a top-level function:
#
#     def register(registry) -> None:
#         ...
#
# That function receives the server's ToolRegistry and should use
# @registry.register(...) to register its tools.
