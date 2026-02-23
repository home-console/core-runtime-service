"""Step 15: Agent Control Plane Module — manages agent enrollment and lifecycle.

Этот пакет экспортирует:
- AgentControlPlaneModule — основная реализация
- AgentModule — alias для ModuleManager (module name "agent")
"""

from modules.agent.module import AgentControlPlaneModule


class AgentModule(AgentControlPlaneModule):
  """
  Backward-compatible alias for AgentControlPlaneModule.

  ModuleManager ищет класс `AgentModule` в пакете `modules.agent`
  для ModuleSpec(name="agent"), поэтому этот alias позволяет загрузить
  агентский control plane без изменения bootstrap.
  """


__all__ = ["AgentControlPlaneModule", "AgentModule"]
