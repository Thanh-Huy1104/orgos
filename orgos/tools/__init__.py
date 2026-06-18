"""orgos.tools — concrete agent tools (CrewAI BaseTool implementations).

These are the hands agents act with. The tool *framework* (GatedToolBase,
ApprovalFn) and the tool-category constants live in the engine at
:mod:`orgos.spawn`. Each module here defines one or more tools; import the
class you need from its submodule, e.g.::

    from orgos.tools.quant_tool import CointegrationScannerTool
    from orgos.tools.research_sources import ArxivSearchTool

BashTool is re-exported here for convenience (and backward compatibility).
"""

from .bash import BashTool

__all__ = ["BashTool"]
