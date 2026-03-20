"""
Semantic Versioning Engine — version resolution and constraint matching.

Step 12: Plugin version resolution with support for:
- Exact: 1.2.3
- Caret: ^1.2.0 (>=1.2.0, <2.0.0)
- Tilde: ~1.2.0 (>=1.2.0, <1.3.0)
- Range: >=1.2.0,<2.0.0
- Pre-release handling
"""

from typing import List, Optional, Tuple
from packaging import version as pkg_version
import re


class VersionConstraintError(Exception):
    """Version constraint parsing or matching failed."""
    pass


class Version:
    """Wrapper for semantic version with comparison."""
    
    def __init__(self, version_string: str):
        """
        Parse semantic version string.
        
        Args:
            version_string: Version in format "1.2.3" or "1.2.3-beta.1"
            
        Raises:
            VersionConstraintError: if invalid format
        """
        try:
            self._parsed = pkg_version.parse(version_string)
            self._original = version_string
        except Exception as e:
            raise VersionConstraintError(f"Invalid version '{version_string}': {e}")
    
    def __str__(self) -> str:
        return self._original
    
    def __eq__(self, other) -> bool:
        if isinstance(other, Version):
            return self._parsed == other._parsed
        return False
    
    def __lt__(self, other) -> bool:
        if isinstance(other, Version):
            return self._parsed < other._parsed
        raise TypeError(f"Cannot compare Version with {type(other)}")
    
    def __le__(self, other) -> bool:
        if isinstance(other, Version):
            return self._parsed <= other._parsed
        raise TypeError(f"Cannot compare Version with {type(other)}")
    
    def __gt__(self, other) -> bool:
        if isinstance(other, Version):
            return self._parsed > other._parsed
        raise TypeError(f"Cannot compare Version with {type(other)}")
    
    def __ge__(self, other) -> bool:
        if isinstance(other, Version):
            return self._parsed >= other._parsed
        raise TypeError(f"Cannot compare Version with {type(other)}")
    
    def is_prerelease(self) -> bool:
        """Check if version is pre-release."""
        return self._parsed.is_prerelease
    
    @property
    def major(self) -> int:
        """Get major version number."""
        return self._parsed.major
    
    @property
    def minor(self) -> int:
        """Get minor version number."""
        return self._parsed.minor
    
    @property
    def patch(self) -> int:
        """Get patch version number."""
        return self._parsed.micro


class VersionConstraint:
    """Semantic version constraint parser and matcher."""
    
    def __init__(self, constraint_string: str):
        """
        Parse version constraint string.
        
        Supports:
        - Exact: "1.2.3"
        - Caret: "^1.2.0" (>=1.2.0, <2.0.0)
        - Tilde: "~1.2.0" (>=1.2.0, <1.3.0)
        - Range: ">=1.2.0,<2.0.0" or ">=1.2.0;<=2.0.0"
        - Multiple constraints: ">=1.0,<2.0,!=1.5.0"
        
        Args:
            constraint_string: Constraint specification
            
        Raises:
            VersionConstraintError: if constraint is invalid
        """
        self._original = constraint_string.strip()
        self._constraints: List[Tuple[str, str]] = []  # List of (operator, version)
        
        self._parse_constraint(self._original)
    
    def _parse_constraint(self, constraint_str: str):
        """Parse constraint string into operator/version pairs."""
        constraint_str = constraint_str.strip()
        
        # Check for caret constraint
        if constraint_str.startswith("^"):
            self._parse_caret(constraint_str[1:])
            return
        
        # Check for tilde constraint
        if constraint_str.startswith("~"):
            self._parse_tilde(constraint_str[1:])
            return
        
        # Check for range constraint (multiple parts)
        if "," in constraint_str or ";" in constraint_str:
            # Split by comma or semicolon
            parts = re.split(r'[,;]', constraint_str)
            for part in parts:
                part = part.strip()
                if part:
                    self._parse_single_constraint(part)
            return
        
        # Single constraint (exact or operator-based)
        if constraint_str and not any(constraint_str.startswith(op) for op in [">=", "<=", ">", "<", "=", "!="]):
            # Exact version
            self._constraints.append(("==", constraint_str))
        else:
            self._parse_single_constraint(constraint_str)
    
    def _parse_single_constraint(self, part: str):
        """Parse single constraint like '>=1.2.0' or '!=1.5.0'."""
        match = re.match(r'^(>=|<=|>|<|!=|=|==)?\s*(.+)$', part.strip())
        if not match:
            raise VersionConstraintError(f"Invalid constraint: {part}")
        
        operator = match.group(1) or "=="
        version_str = match.group(2).strip()
        
        # Normalize operators
        if operator == "=":
            operator = "=="
        
        try:
            Version(version_str)  # Validate version string
            self._constraints.append((operator, version_str))
        except VersionConstraintError as e:
            raise VersionConstraintError(f"Invalid version in constraint: {e}")
    
    def _parse_caret(self, version_str: str):
        """Parse caret constraint: ^1.2.3 -> >=1.2.3, <2.0.0."""
        try:
            ver = Version(version_str)
        except VersionConstraintError as e:
            raise VersionConstraintError(f"Invalid caret constraint: {e}")
        
        # ^1.2.3 -> >=1.2.3, <2.0.0
        # ^0.2.3 -> >=0.2.3, <0.3.0
        # ^0.0.3 -> >=0.0.3, <0.0.4
        
        self._constraints.append((">=", version_str))
        
        if ver.major > 0:
            upper = f"{ver.major + 1}.0.0"
        elif ver.minor > 0:
            upper = f"0.{ver.minor + 1}.0"
        else:
            upper = f"0.0.{ver.patch + 1}"
        
        self._constraints.append(("<", upper))
    
    def _parse_tilde(self, version_str: str):
        """Parse tilde constraint: ~1.2.3 -> >=1.2.3, <1.3.0."""
        try:
            ver = Version(version_str)
        except VersionConstraintError as e:
            raise VersionConstraintError(f"Invalid tilde constraint: {e}")
        
        # ~1.2.3 -> >=1.2.3, <1.3.0
        # ~1.2   -> >=1.2.0, <1.3.0
        
        self._constraints.append((">=", version_str))
        upper = f"{ver.major}.{ver.minor + 1}.0"
        self._constraints.append(("<", upper))
    
    def matches(self, version: Version) -> bool:
        """Check if version matches all constraints."""
        for operator, constraint_version in self._constraints:
            constraint_ver = Version(constraint_version)
            
            if operator == "==":
                if not version == constraint_ver:
                    return False
            elif operator == "!=":
                if version == constraint_ver:
                    return False
            elif operator == ">":
                if not version > constraint_ver:
                    return False
            elif operator == ">=":
                if not version >= constraint_ver:
                    return False
            elif operator == "<":
                if not version < constraint_ver:
                    return False
            elif operator == "<=":
                if not version <= constraint_ver:
                    return False
        
        return True
    
    def __str__(self) -> str:
        return self._original


class VersionResolver:
    """
    Resolve plugin version from list of available versions.
    
    Finds best matching version given constraint.
    """
    
    def __init__(self, available_versions: List[str], include_prerelease: bool = False):
        """
        Initialize resolver with available versions.
        
        Args:
            available_versions: List of version strings
            include_prerelease: Whether to include pre-release versions
        """
        self._versions = [Version(v) for v in available_versions]
        self._include_prerelease = include_prerelease
    
    def resolve(self, constraint: str) -> Optional[Version]:
        """
        Resolve best matching version for constraint.
        
        Returns highest version that matches constraint,
        or None if no match found.
        
        Args:
            constraint: Version constraint string
            
        Returns:
            Matching Version or None
            
        Raises:
            VersionConstraintError: if constraint is invalid
        """
        try:
            constraint_obj = VersionConstraint(constraint)
        except VersionConstraintError as e:
            raise VersionConstraintError(f"Failed to resolve '{constraint}': {e}")
        
        # Filter versions
        matching = []
        for ver in self._versions:
            # Skip pre-release unless enabled
            if ver.is_prerelease() and not self._include_prerelease:
                continue
            
            # Check constraint
            if constraint_obj.matches(ver):
                matching.append(ver)
        
        if not matching:
            return None
        
        # Return highest matching version
        return sorted(matching, reverse=True)[0]
    
    def resolve_all(self, constraint: str) -> List[Version]:
        """
        Get all versions matching constraint, sorted descending.
        
        Args:
            constraint: Version constraint string
            
        Returns:
            List of matching versions (highest first)
        """
        try:
            constraint_obj = VersionConstraint(constraint)
        except VersionConstraintError as e:
            raise VersionConstraintError(f"Failed to resolve '{constraint}': {e}")
        
        matching = []
        for ver in self._versions:
            if constraint_obj.matches(ver):
                matching.append(ver)
        
        return sorted(matching, reverse=True)
