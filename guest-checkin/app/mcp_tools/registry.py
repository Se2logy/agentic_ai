"""Tool registry — registers all MCP tools and provides lookup/description APIs.

The ToolRegistry collects all tool handlers with their metadata
(name, description, parameters schema) so the LLM agent can
discover available tools and invoke them by name.
"""

import logging
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Type alias for tool handler functions
ToolHandler = Callable[..., Awaitable[dict[str, Any] | None]]


class ToolDefinition:
    """A registered MCP tool with its metadata and handler."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: ToolHandler,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def to_dict(self) -> dict[str, Any]:
        """Serialize for LLM system prompt inclusion."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Registry of all MCP tools available to the LLM agent.

    Usage::

        registry = ToolRegistry()
        registry.register_all()

        # Get tool descriptions for LLM system prompt
        descriptions = registry.get_tool_descriptions()

        # Get a specific tool handler
        handler = registry.get_tool("get_reservation")
        result = await handler(db_session, booking_reference="BK-001")
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: ToolHandler,
    ) -> None:
        """Register a tool with its metadata and handler function."""
        if name in self._tools:
            logger.warning("Overwriting already-registered tool: %s", name)
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )
        logger.debug("Registered tool: %s", name)

    def get_tool(self, name: str) -> ToolHandler | None:
        """Get a tool's handler function by name.

        Returns None if the tool is not registered.
        """
        tool_def = self._tools.get(name)
        if tool_def is None:
            return None
        return tool_def.handler

    def get_tool_descriptions(self) -> list[dict[str, Any]]:
        """Get all tool descriptions as a list of dicts.

        Suitable for inclusion in the LLM system prompt so the
        agent knows which tools are available and how to call them.
        """
        return [tool.to_dict() for tool in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """Get a sorted list of all registered tool names."""
        return sorted(self._tools.keys())

    def register_all(self) -> None:
        """Register all 12 MCP tools from the tool modules.

        This is the main entry point — call once at app startup.
        """
        # 1. get_reservation
        from app.mcp_tools.reservation_tools import (
            TOOL_NAME as name,
            TOOL_DESCRIPTION as desc,
            TOOL_PARAMETERS as params,
            get_reservation as handler,
        )
        self.register(name, desc, params, handler)

        # 2. record_agreement
        from app.mcp_tools.agreement_tools import (
            TOOL_NAME as name,
            TOOL_DESCRIPTION as desc,
            TOOL_PARAMETERS as params,
            record_agreement as handler,
        )
        self.register(name, desc, params, handler)

        # 3. update_guest_info
        from app.mcp_tools.guest_tools import (
            TOOL_NAME as name,
            TOOL_DESCRIPTION as desc,
            TOOL_PARAMETERS as params,
            update_guest_info as handler,
        )
        self.register(name, desc, params, handler)

        # 4. trigger_otp
        from app.mcp_tools.otp_tools import (
            TRIGGER_TOOL_NAME as name,
            TRIGGER_TOOL_DESCRIPTION as desc,
            TRIGGER_TOOL_PARAMETERS as params,
            trigger_otp as handler,
        )
        self.register(name, desc, params, handler)

        # 5. verify_otp
        from app.mcp_tools.otp_tools import (
            VERIFY_TOOL_NAME as name,
            VERIFY_TOOL_DESCRIPTION as desc,
            VERIFY_TOOL_PARAMETERS as params,
            verify_otp as handler,
        )
        self.register(name, desc, params, handler)

        # 6. generate_id_upload_link
        from app.mcp_tools.id_upload_tools import (
            GENERATE_TOOL_NAME as name,
            GENERATE_TOOL_DESCRIPTION as desc,
            GENERATE_TOOL_PARAMETERS as params,
            generate_id_upload_link as handler,
        )
        self.register(name, desc, params, handler)

        # 7. record_id_upload
        from app.mcp_tools.id_upload_tools import (
            RECORD_TOOL_NAME as name,
            RECORD_TOOL_DESCRIPTION as desc,
            RECORD_TOOL_PARAMETERS as params,
            record_id_upload as handler,
        )
        self.register(name, desc, params, handler)

        # 8. generate_incidental_link
        from app.mcp_tools.incidental_tools import (
            GENERATE_TOOL_NAME as name,
            GENERATE_TOOL_DESCRIPTION as desc,
            GENERATE_TOOL_PARAMETERS as params,
            generate_incidental_link as handler,
        )
        self.register(name, desc, params, handler)

        # 9. record_incidental_selection
        from app.mcp_tools.incidental_tools import (
            RECORD_TOOL_NAME as name,
            RECORD_TOOL_DESCRIPTION as desc,
            RECORD_TOOL_PARAMETERS as params,
            record_incidental_selection as handler,
        )
        self.register(name, desc, params, handler)

        # 10. get_arrival_instructions
        from app.mcp_tools.arrival_tools import (
            TOOL_NAME as name,
            TOOL_DESCRIPTION as desc,
            TOOL_PARAMETERS as params,
            get_arrival_instructions as handler,
        )
        self.register(name, desc, params, handler)

        # 11. get_faq_answer
        from app.mcp_tools.faq_tools import (
            FAQ_TOOL_NAME as name,
            FAQ_TOOL_DESCRIPTION as desc,
            FAQ_TOOL_PARAMETERS as params,
            get_faq_answer as handler,
        )
        self.register(name, desc, params, handler)

        # 12. get_current_state
        from app.mcp_tools.faq_tools import (
            STATE_TOOL_NAME as name,
            STATE_TOOL_DESCRIPTION as desc,
            STATE_TOOL_PARAMETERS as params,
            get_current_state as handler,
        )
        self.register(name, desc, params, handler)

        logger.info(
            "Registered %d MCP tools: %s",
            len(self._tools),
            ", ".join(self.get_tool_names()),
        )


# Singleton instance — import and call .register_all() at startup
tool_registry = ToolRegistry()
