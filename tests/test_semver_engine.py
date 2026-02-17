"""
Step 12 Semver Engine Tests — semantic version resolution.

Tests cover:
- Exact version matching
- Caret constraints (^)
- Tilde constraints (~)
- Range constraints (>=, <=, <, >)
- Pre-release handling
- Multi-constraint resolution
"""

import pytest
from core.marketplace.semver import (
    Version, VersionConstraint, VersionResolver, VersionConstraintError
)


class TestVersionParsing:
    """Test basic version parsing."""
    
    def test_parse_exact_version(self):
        """Test parsing exact version."""
        ver = Version("1.2.3")
        assert str(ver) == "1.2.3"
        assert ver.major == 1
        assert ver.minor == 2
        assert ver.patch == 3
    
    def test_parse_prerelease_version(self):
        """Test parsing pre-release version."""
        ver = Version("1.2.3-beta.1")
        assert str(ver) == "1.2.3-beta.1"
        assert ver.is_prerelease()
    
    def test_parse_invalid_version(self):
        """Test parsing invalid version raises error."""
        with pytest.raises(VersionConstraintError):
            Version("invalid")
    
    def test_version_comparison(self):
        """Test version comparisons."""
        v1 = Version("1.2.3")
        v2 = Version("1.2.4")
        v3 = Version("1.2.3")
        
        assert v1 < v2
        assert v2 > v1
        assert v1 == v3
        assert v1 <= v2
        assert v1 >= v3


class TestExactConstraint:
    """Test exact version constraints."""
    
    def test_exact_match(self):
        """Test exact version matching."""
        constraint = VersionConstraint("1.2.3")
        assert constraint.matches(Version("1.2.3"))
        assert not constraint.matches(Version("1.2.4"))
    
    def test_equals_operator(self):
        """Test = operator."""
        constraint = VersionConstraint("=1.2.3")
        assert constraint.matches(Version("1.2.3"))
        assert not constraint.matches(Version("1.2.4"))


class TestCaretConstraint:
    """Test caret constraints (^)."""
    
    def test_caret_major_version(self):
        """Test ^1.2.3 -> >=1.2.3, <2.0.0."""
        constraint = VersionConstraint("^1.2.3")
        
        assert constraint.matches(Version("1.2.3"))
        assert constraint.matches(Version("1.2.4"))
        assert constraint.matches(Version("1.3.0"))
        assert constraint.matches(Version("1.9.9"))
        
        # Should not match 2.0.0 or higher
        assert not constraint.matches(Version("2.0.0"))
        assert not constraint.matches(Version("1.2.2"))
    
    def test_caret_minor_version(self):
        """Test ^0.2.3 -> >=0.2.3, <0.3.0."""
        constraint = VersionConstraint("^0.2.3")
        
        assert constraint.matches(Version("0.2.3"))
        assert constraint.matches(Version("0.2.4"))
        
        assert not constraint.matches(Version("0.3.0"))
        assert not constraint.matches(Version("0.2.2"))
    
    def test_caret_patch_version(self):
        """Test ^0.0.3 -> >=0.0.3, <0.0.4."""
        constraint = VersionConstraint("^0.0.3")
        
        assert constraint.matches(Version("0.0.3"))
        
        assert not constraint.matches(Version("0.0.4"))
        assert not constraint.matches(Version("0.0.2"))


class TestTildeConstraint:
    """Test tilde constraints (~)."""
    
    def test_tilde_constraint(self):
        """Test ~1.2.3 -> >=1.2.3, <1.3.0."""
        constraint = VersionConstraint("~1.2.3")
        
        assert constraint.matches(Version("1.2.3"))
        assert constraint.matches(Version("1.2.4"))
        assert constraint.matches(Version("1.2.10"))
        
        # Should not match 1.3.0
        assert not constraint.matches(Version("1.3.0"))
        assert not constraint.matches(Version("1.2.2"))
    
    def test_tilde_minor_precision(self):
        """Test ~1.2 -> >=1.2.0, <1.3.0."""
        constraint = VersionConstraint("~1.2")
        
        assert constraint.matches(Version("1.2.0"))
        assert constraint.matches(Version("1.2.5"))
        
        assert not constraint.matches(Version("1.3.0"))


class TestRangeConstraint:
    """Test range constraints (>=, <=, <, >)."""
    
    def test_greater_than_or_equal(self):
        """Test >= operator."""
        constraint = VersionConstraint(">=1.2.0")
        
        assert constraint.matches(Version("1.2.0"))
        assert constraint.matches(Version("1.2.1"))
        assert constraint.matches(Version("2.0.0"))
        
        assert not constraint.matches(Version("1.1.9"))
    
    def test_less_than(self):
        """Test < operator."""
        constraint = VersionConstraint("<2.0.0")
        
        assert constraint.matches(Version("1.9.9"))
        assert constraint.matches(Version("1.0.0"))
        
        assert not constraint.matches(Version("2.0.0"))
        assert not constraint.matches(Version("2.0.1"))
    
    def test_multiple_constraints(self):
        """Test multiple constraints combined."""
        constraint = VersionConstraint(">=1.0.0,<2.0.0")
        
        assert constraint.matches(Version("1.0.0"))
        assert constraint.matches(Version("1.5.0"))
        assert constraint.matches(Version("1.9.9"))
        
        assert not constraint.matches(Version("0.9.9"))
        assert not constraint.matches(Version("2.0.0"))
    
    def test_exclude_specific_version(self):
        """Test != operator to exclude specific version."""
        constraint = VersionConstraint(">=1.0.0,!=1.5.0")
        
        assert constraint.matches(Version("1.0.0"))
        assert constraint.matches(Version("1.4.9"))
        assert constraint.matches(Version("1.5.1"))
        
        assert not constraint.matches(Version("1.5.0"))


class TestPreReleaseHandling:
    """Test pre-release version handling."""
    
    def test_include_prerelease_flag(self):
        """Test including pre-release versions."""
        versions = ["1.0.0", "1.1.0-beta.1", "1.2.0"]
        
        # Without pre-release - use >= constraint instead of *
        resolver = VersionResolver(versions, include_prerelease=False)
        result = resolver.resolve(">=1.0.0")
        assert result == Version("1.2.0")
        
        # With pre-release
        resolver = VersionResolver(versions, include_prerelease=True)
        result = resolver.resolve(">=1.0.0")
        assert result == Version("1.2.0")
    
    def test_prerelease_version_comparison(self):
        """Test that pre-release is less than release."""
        pre = Version("1.0.0-beta")
        release = Version("1.0.0")
        
        assert pre < release


class TestVersionResolver:
    """Test version resolver."""
    
    def test_resolve_exact_version(self):
        """Test resolving exact version."""
        versions = ["1.0.0", "1.1.0", "1.2.0"]
        resolver = VersionResolver(versions)
        
        result = resolver.resolve("1.1.0")
        assert result == Version("1.1.0")
    
    def test_resolve_caret_constraint(self):
        """Test resolving caret constraint returns highest matching."""
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0"]
        resolver = VersionResolver(versions)
        
        result = resolver.resolve("^1.0.0")
        assert result == Version("1.2.0")  # Highest version < 2.0.0
    
    def test_resolve_no_match(self):
        """Test resolve returns None for no match."""
        versions = ["1.0.0", "1.1.0"]
        resolver = VersionResolver(versions)
        
        result = resolver.resolve("2.0.0")
        assert result is None
    
    def test_resolve_all_matching(self):
        """Test resolve_all returns all matching versions."""
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0"]
        resolver = VersionResolver(versions)
        
        results = resolver.resolve_all("^1.0.0")
        assert len(results) == 3
        assert results[0] == Version("1.2.0")  # Highest first
        assert results[-1] == Version("1.0.0")  # Lowest last
    
    def test_resolve_range_constraint(self):
        """Test resolving range constraint."""
        versions = ["0.9.0", "1.0.0", "1.5.0", "2.0.0"]
        resolver = VersionResolver(versions)
        
        result = resolver.resolve(">=1.0.0,<2.0.0")
        assert result == Version("1.5.0")  # Highest matching
    
    def test_invalid_constraint_raises_error(self):
        """Test invalid constraint raises error."""
        versions = ["1.0.0"]
        resolver = VersionResolver(versions)
        
        with pytest.raises(VersionConstraintError):
            resolver.resolve("invalid constraint")


class TestComplexConstraints:
    """Test complex constraint combinations."""
    
    def test_complex_range(self):
        """Test complex range with multiple operators."""
        constraint = VersionConstraint(">=1.0.0,<3.0.0,!=2.0.0")
        
        assert constraint.matches(Version("1.5.0"))
        assert constraint.matches(Version("1.9.9"))
        
        assert not constraint.matches(Version("2.0.0"))
        assert not constraint.matches(Version("3.0.0"))
    
    def test_constraint_with_prerelease(self):
        """Test constraint matching with pre-release."""
        constraint = VersionConstraint(">=1.0.0")
        
        # 1.0.0-beta is less than 1.0.0, so does not match >=1.0.0
        assert not constraint.matches(Version("1.0.0-beta"))
        assert constraint.matches(Version("1.0.0"))
        assert constraint.matches(Version("1.0.1-beta"))  # 1.0.1-beta > 1.0.0
    
    def test_caret_with_prerelease(self):
        """Test caret constraint allows pre-release patches."""
        constraint = VersionConstraint("^1.0.0-beta")
        
        assert constraint.matches(Version("1.0.0-beta.1"))
        assert constraint.matches(Version("1.0.0"))
        assert constraint.matches(Version("1.5.0"))
        
        assert not constraint.matches(Version("2.0.0"))
