"""
Module Dependency Sorter — сортировка модулей по зависимостям.

Отвечает ТОЛЬКО за:
- Топологическую сортировку спецификаций модулей
- Обнаружение циклических зависимостей
- Валидацию что все зависимости разрешены

НЕ отвечает за:
- Обнаружение модулей (import)
- Lifecycle модулей (register/start/stop)
- Хранение зарегистрированных модулей
"""

from typing import Dict, List, Set

from core.module_spec import ModuleSpec


class ModuleDependencySorter:
    """
    Сортировка модулей по зависимостям.

    Использует топологическую сортировку для определения правильного порядка загрузки.
    """

    def order_by_dependencies(self, specs: List[ModuleSpec]) -> List[ModuleSpec]:
        """
        Переставить specs так, чтобы зависимости гарантировали корректный порядок.
        
        Алгоритм:
        - Kahn's algorithm для топологической сортировки
        - Стабильная сортировка: при равном уровне зависимостей сохраняется исходный порядок
        - Обнаружение циклов и неразрешённых зависимостей
        
        Args:
            specs: список спецификаций модулей
            
        Returns:
            Отсортированный список спецификаций
            
        Raises:
            RuntimeError: если обнаружен цикл или неразрешённая зависимость
            RuntimeError: если есть дубликаты имён
        """
        if len(specs) <= 1:
            return specs

        # Build indexes
        name_to_spec: Dict[str, ModuleSpec] = {}
        index: Dict[str, int] = {}
        for i, s in enumerate(specs):
            if s.name in name_to_spec:
                raise RuntimeError(f"Duplicate ModuleSpec name '{s.name}' in specs list")
            name_to_spec[s.name] = s
            index[s.name] = i

        # Build dependency graph
        deps: Dict[str, Set[str]] = {s.name: set(s.dependencies or []) for s in specs}
        
        # Validate all dependencies are present
        for s_name, dep_set in deps.items():
            for dep_name in dep_set:
                if dep_name not in name_to_spec:
                    raise RuntimeError(
                        f"Module '{s_name}' depends on '{dep_name}', but '{dep_name}' is not present in ModuleSpec list"
                    )

        # Build adjacency list for topological sort
        outgoing: Dict[str, Set[str]] = {name: set() for name in deps}
        indegree: Dict[str, int] = {name: len(dep_set) for name, dep_set in deps.items()}
        
        for node, dep_set in deps.items():
            for dep in dep_set:
                outgoing[dep].add(node)

        # Kahn's algorithm
        ready = [name for name, deg in indegree.items() if deg == 0]
        ready.sort(key=lambda n: index[n])

        ordered: List[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for nxt in sorted(outgoing[current], key=lambda n: index[n]):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
                    ready.sort(key=lambda n: index[n])

        if len(ordered) != len(specs):
            raise RuntimeError("Cyclic or unresolved module dependencies detected in ModuleSpec list")

        return [name_to_spec[name] for name in ordered]

    def detect_cycles(self, specs: List[ModuleSpec]) -> List[str]:
        """
        Обнаружить циклические зависимости.
        
        Args:
            specs: список спецификаций модулей
            
        Returns:
            Список имён модулей участвующих в циклах (пустой если циклов нет)
        """
        # Build graph
        deps: Dict[str, Set[str]] = {s.name: set(s.dependencies or []) for s in specs}
        name_to_spec: Dict[str, "ModuleSpec"] = {s.name: s for s in specs}
        
        # DFS for cycle detection
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {name: WHITE for name in deps}
        cycle_nodes: Set[str] = set()

        def dfs(node: str, path: List[str]) -> bool:
            color[node] = GRAY
            path.append(node)

            for neighbor in deps.get(node, set()):
                if neighbor not in name_to_spec:
                    continue  # Skip missing deps
                if color[neighbor] == GRAY:
                    # Found cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:]
                    cycle_nodes.update(cycle)
                    return True
                elif color[neighbor] == WHITE:
                    if dfs(neighbor, path):
                        return True

            path.pop()
            color[node] = BLACK
            return False

        for name in deps:
            if color[name] == WHITE:
                dfs(name, [])

        return list(cycle_nodes)
