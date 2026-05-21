"""Platform skills registry — declarations from plugin.json (not Agent Control Plane)."""

from modules.skills.module import SkillsModule
from modules.skills.registry import SkillRecord, SkillRegistry

__all__ = ["SkillRecord", "SkillRegistry", "SkillsModule"]
