"""
Step 12 Simplified Integration Tests — focus on core logic.

Simplified tests that focus on main workflows without all the async/mock complexity.
"""

import pytest
from modules.marketplace.semver import Version, VersionConstraint, VersionResolver


class TestSemverIntegration:
    """Integration tests for semver engine."""
    
    def test_resolve_caret_constraint_correctly(self):
        """Test caret constraint resolution works correctly."""
        versions = ["1.0.0", "1.1.5", "1.9.9", "2.0.0", "2.1.0"]
        resolver = VersionResolver(versions)
        
        result = resolver.resolve("^1.0.0")
        assert str(result) == "1.9.9"  # Highest version < 2.0.0
    
    def test_resolve_tilde_constraint_correctly(self):
        """Test tilde constraint resolution works correctly."""
        versions = ["1.2.0", "1.2.3", "1.2.9", "1.3.0", "2.0.0"]
        resolver = VersionResolver(versions)
        
        result = resolver.resolve("~1.2.0")
        assert str(result) == "1.2.9"  # Highest patch version
    
    def test_resolve_range_with_multiple_constraints(self):
        """Test resolving range with multiple constraints."""
        versions = ["0.5.0", "1.0.0", "1.5.0", "2.0.0", "2.5.0"]
        resolver = VersionResolver(versions)
        
        # >= 1.0.0 AND < 2.5.0
        result = resolver.resolve(">=1.0.0,<2.5.0")
        assert str(result) == "2.0.0"  # Highest matching
    
    def test_resolve_finds_highest_matching(self):
        """Test that resolver finds highest matching version."""
        versions = ["1.0.0", "1.1.0", "1.1.1", "1.1.2", "1.2.0", "2.0.0"]
        resolver = VersionResolver(versions)
        
        # Should return 1.2.0 as highest < 2.0.0
        result = resolver.resolve("^1.0.0")
        assert str(result) == "1.2.0"
    
    def test_constraint_excludes_versions(self):
        """Test that constraints properly exclude versions."""
        # Test simple != constraint
        constraint = VersionConstraint("!=1.5.0")
        
        assert constraint.matches(Version("1.0.0"))
        assert constraint.matches(Version("1.4.0"))
        assert not constraint.matches(Version("1.5.0"))  # Excluded
        assert constraint.matches(Version("1.5.1"))
        assert constraint.matches(Version("2.0.0"))
    
    def test_semver_special_versions(self):
        """Test handling of special versions."""
        versions = ["0.0.1", "0.1.0", "0.2.0", "1.0.0-alpha", "1.0.0"]
        resolver = VersionResolver(versions, include_prerelease=False)
        
        # Should skip pre-release and find 1.0.0
        result = resolver.resolve(">=0.0.1")
        assert str(result) == "1.0.0"


class TestVersionComparison:
    """Test version comparison operators."""
    
    def test_version_less_than(self):
        """Test less than comparison."""
        v1 = Version("1.0.0")
        v2 = Version("1.0.1")
        assert v1 < v2
    
    def test_version_greater_than(self):
        """Test greater than comparison."""
        v1 = Version("2.0.0")
        v2 = Version("1.9.9")
        assert v1 > v2
    
    def test_version_equal(self):
        """Test equality comparison."""
        v1 = Version("1.5.0")
        v2 = Version("1.5.0")
        assert v1 == v2
    
    def test_version_prerelease_is_less(self):
        """Test that pre-release is less than release."""
        pre = Version("2.0.0-rc")
        release = Version("2.0.0")
        assert pre < release


class TestConstraintPatterns:
    """Test various constraint patterns."""
    
    def test_exact_version_matching(self):
        """Test exact version matching."""
        constraint = VersionConstraint("1.2.3")
        
        assert constraint.matches(Version("1.2.3"))
        assert not constraint.matches(Version("1.2.4"))
        assert not constraint.matches(Version("1.2.2"))
    
    def test_wildcard_ranges(self):
        """Test wildcard-style ranges."""
        # ^X.Y.0 should work
        constraint = VersionConstraint("^1.2.0")
        assert constraint.matches(Version("1.2.0"))
        assert constraint.matches(Version("1.9.99"))
        assert not constraint.matches(Version("2.0.0"))
    
    def test_combined_gt_and_lt(self):
        """Test combined greater than and less than."""
        constraint = VersionConstraint(">1.0.0,<2.0.0")
        
        assert not constraint.matches(Version("1.0.0"))  # Not >=
        assert constraint.matches(Version("1.0.1"))
        assert constraint.matches(Version("1.9.9"))
        assert not constraint.matches(Version("2.0.0"))
    
    def test_geq_and_leq(self):
        """Test >= and <=."""
        constraint = VersionConstraint(">=1.0.0,<=2.0.0")
        
        assert constraint.matches(Version("1.0.0"))
        assert constraint.matches(Version("1.5.0"))
        assert constraint.matches(Version("2.0.0"))
        assert not constraint.matches(Version("0.9.9"))
        assert not constraint.matches(Version("2.0.1"))


class TestDowngradeDetection:
    """Test downgrade detection logic."""
    
    def test_patch_downgrade_detected(self):
        """Test that patch version downgrade is detected."""
        current = Version("1.0.5")
        candidate = Version("1.0.3")
        
        assert candidate < current  # Downgrade detected
    
    def test_minor_downgrade_detected(self):
        """Test that minor version downgrade is detected."""
        current = Version("2.0.0")
        candidate = Version("1.9.9")
        
        assert candidate < current
    
    def test_major_downgrade_detected(self):
        """Test that major version downgrade is detected."""
        current = Version("3.0.0")
        candidate = Version("2.99.99")
        
        assert candidate < current
    
    def test_upgrade_not_downgrade(self):
        """Test that upgrades are not downgrades."""
        current = Version("1.0.0")
        candidate = Version("1.0.1")
        
        assert candidate > current  # Upgrade, not downgrade


class TestVersionResolverEdgeCases:
    """Test edge cases in version resolver."""
    
    def test_single_version_available(self):
        """Test resolution with single version available."""
        versions = ["1.0.0"]
        resolver = VersionResolver(versions)
        
        result = resolver.resolve("1.0.0")
        assert result == Version("1.0.0")
    
    def test_no_matching_version(self):
        """Test resolution when no version matches."""
        versions = ["1.0.0", "1.1.0"]
        resolver = VersionResolver(versions)
        
        result = resolver.resolve("2.0.0")
        assert result is None
    
    def test_resolve_all_versions_matching(self):
        """Test getting all matching versions."""
        versions = ["1.0.0", "1.1.0", "1.2.0", "2.0.0"]
        resolver = VersionResolver(versions)
        
        results = resolver.resolve_all("^1.0.0")
        
        # Should return 1.2.0, 1.1.0, 1.0.0 in order (highest first)
        assert len(results) == 3
        assert results[0] == Version("1.2.0")
        assert results[-1] == Version("1.0.0")
    
    def test_resolve_with_prerelease_filtering(self):
        """Test that pre-releases are filtered out."""
        versions = ["1.0.0", "1.1.0-beta", "1.2.0", "2.0.0-rc"]
        resolver = VersionResolver(versions, include_prerelease=False)
        
        result = resolver.resolve(">=1.0.0")
        
        # Should skip pre-releases and return 1.2.0
        assert str(result) == "1.2.0"


class TestMarketplaceWorkflows:
    """Test complete marketplace workflows."""
    
    def test_version_resolution_workflow(self):
        """Test complete version resolution workflow."""
        # Simulate registry having these versions
        available_versions = [
            "1.0.0",
            "1.1.0", 
            "1.2.0",
            "1.2.1",
            "2.0.0-beta",
            "2.0.0"
        ]
        
        resolver = VersionResolver(available_versions)
        
        # User requests: "give me a compatible 1.*"
        result = resolver.resolve("^1.0.0")
        
        # Should get highest 1.x version (not 2.0.0-beta or 2.0.0)
        assert str(result) == "1.2.1"
    
    def test_multiple_constraint_patterns(self):
        """Test various constraint patterns in workflow."""
        versions = ["0.8.0", "1.0.0", "1.5.0", "2.0.0", "2.5.0", "3.0.0"]
        
        # Test pattern 1: ^1.0.0
        resolver1 = VersionResolver(versions)
        assert str(resolver1.resolve("^1.0.0")) == "1.5.0"
        
        # Test pattern 2: ~2.0.0
        resolver2 = VersionResolver(versions)
        assert str(resolver2.resolve("~2.0.0")) == "2.0.0"  # Only 2.0.0 matches
        
        # Test pattern 3: >=2.0.0,<3.0.0
        resolver3 = VersionResolver(versions)
        assert str(resolver3.resolve(">=2.0.0,<3.0.0")) == "2.5.0"
