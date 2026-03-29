#!/bin/bash
# FLOW: Run Chaos & Security Validation Suite
# 
# This script validates the entire flow security architecture:
# • Crash safety
# • Rollback resistance
# • Memory protection
# • Session control
# • Concurrent safety
# • Tamper detection
# • Performance impact
# • Threat gap analysis
#
# Usage: ./run_step_16_5_validation.sh

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR"  # Tests are in this directory

echo ""
echo "=========================================="
echo "FLOW: CHAOS & SECURITY VALIDATION"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check Python
echo -e "${BLUE}[1/4]${NC} Checking Python environment..."
python3 --version
python3 -c "import pytest; print(f'pytest {pytest.__version__}')" || {
    echo -e "${YELLOW}Warning: pytest not found. Install with: pip install pytest pytest-asyncio${NC}"
}

echo ""

# Check Linux
if [[ "$OSTYPE" == "linux"* ]]; then
    echo -e "${GREEN}✓${NC} Linux system detected (full validation)"
else
    echo -e "${YELLOW}⚠${NC} Non-Linux system (memory security tests will be skipped)"
fi

echo ""

# Part 1-6: Chaos validation
if [ "$1" != "--analysis-only" ]; then
    echo -e "${BLUE}[2/4]${NC} Running Chaos Validation Tests..."
    echo "  • Crash safety validation"
    echo "  • Rollback attack simulation"
    echo "  • Memory security validation"
    echo "  • Session TTL chaos tests"
    echo "  • Concurrent write stress tests"
    echo "  • Tamper detection validation"
    echo ""
    
    cd "$PROJECT_ROOT"
    
    if python3 -m pytest tests/test_security_chaos_validation.py -v --tb=short; then
        echo -e "${GREEN}✓ All chaos tests passed${NC}"
    else
        echo -e "${RED}✗ Some chaos tests failed${NC}"
        exit 1
    fi
    
    echo ""
fi

# Part 7-8: Performance & threat analysis
echo -e "${BLUE}[3/4]${NC} Running Performance & Threat Analysis..."
echo "  • Performance impact measurements"
echo "  • Threat gap analysis (16 scenarios)"
echo ""

cd "$PROJECT_ROOT"

if python3 tests/step_16_5_performance_analysis.py; then
    echo -e "${GREEN}✓ Analysis complete${NC}"
    echo ""
    
    # Check generated files
    if [ -f "STEP_16_5_PERFORMANCE_REPORT.md" ]; then
        echo -e "${GREEN}✓${NC} Performance report: STEP_16_5_PERFORMANCE_REPORT.md"
    fi
    
    if [ -f "STEP_16_5_THREAT_ANALYSIS.md" ]; then
        echo -e "${GREEN}✓${NC} Threat analysis: STEP_16_5_THREAT_ANALYSIS.md"
    fi
else
    echo -e "${RED}✗ Analysis failed${NC}"
    exit 1
fi

echo ""

# Summary
echo -e "${BLUE}[4/4]${NC} Summary"
echo "=========================================="
echo ""
echo -e "${GREEN}✓ FLOW VALIDATION COMPLETE${NC}"
echo ""
echo "Generated Reports:"
echo "  • STEP_16_5_CHAOS_VALIDATION.md — How-to guide"
echo "  • STEP_16_5_DELIVERABLES.md — Summary of deliverables"
echo "  • STEP_16_5_PERFORMANCE_REPORT.md — Performance metrics"
echo "  • STEP_16_5_THREAT_ANALYSIS.md — Threat gap analysis"
echo ""
echo "Expected Maturity Score: 8.0+/10"
echo "Expected Verdict: SAFE TO DEPLOY WITH CAVEATS"
echo ""
echo "Next Steps:"
echo "  1. Review STEP_16_5_THREAT_ANALYSIS.md"
echo "  2. Deploy to staging with CAP_IPC_LOCK"
echo "  3. Plan flow (mTLS & control plane security)"
echo ""
