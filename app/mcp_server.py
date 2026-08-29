from __future__ import annotations

import logging

from mcp.server import MCPServer

from app.config import Settings
from app.db import Database
from app.mcp_functions import InsightForgeMCPFunctions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = Settings.from_env()
database = Database(settings.database_path)
database.init_schema()
database.seed_demo_data()
functions = InsightForgeMCPFunctions(database)

mcp = MCPServer(
    "InsightForge",
    instructions=(
        "Read only the current confirmed project context exposed by InsightForge. "
        "Preserve evidence boundaries and never confirm, publish, delete, or overwrite artifacts."
    ),
)


@mcp.resource("insightforge://projects/{project_id}/snapshot/current")
def current_snapshot(project_id: str) -> dict:
    """Read the current confirmed Project Snapshot."""
    return functions.get_current_snapshot_resource(project_id)


@mcp.resource("insightforge://projects/{project_id}/documents/prd/current")
def current_prd(project_id: str) -> dict:
    """Read the current confirmed healthy PRD."""
    return functions.get_current_document_resource(project_id, "prd")


@mcp.resource("insightforge://projects/{project_id}/documents/techdoc/current")
def current_techdoc(project_id: str) -> dict:
    """Read the current confirmed healthy TechDoc."""
    return functions.get_current_document_resource(project_id, "techdoc")


@mcp.resource("insightforge://projects/{project_id}/mvp-scope")
def current_mvp_scope(project_id: str) -> dict:
    """Read MVP scope from the current Snapshot."""
    return functions.get_mvp_scope_resource(project_id)


@mcp.resource("insightforge://projects/{project_id}/unresolved-risks")
def current_unresolved_risks(project_id: str) -> dict:
    """Read unresolved risks and the next recommended validation action."""
    return functions.get_unresolved_risks_resource(project_id)


@mcp.tool()
def get_current_project_context(project_id: str) -> dict:
    """Read current Snapshot and, when ready, current confirmed healthy documents."""
    return functions.get_current_project_context(project_id)


@mcp.tool()
def build_handoff_manifest(project_id: str, target_client: str = "codex") -> dict:
    """Build a non-binary manifest preview for the current healthy project context."""
    return functions.build_handoff_manifest(project_id, target_client)


if __name__ == "__main__":
    logger.info("Starting InsightForge MCP server over STDIO")
    mcp.run(transport="stdio")
