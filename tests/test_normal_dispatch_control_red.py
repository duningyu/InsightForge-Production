"""Defect-reproduction tests for normal managed dispatch control.

These tests intentionally describe the missing integration at the start of
the remediation.  They must fail for the missing contract, not for imports
or fixture setup.
"""

import inspect

from app.services.ai_runtime import ManagedModelStructuredRuntime
from app.services.async_generation import AsyncGenerationRepository
from app.services.solution_design import SolutionDesignService


def test_normal_async_repository_can_carry_dispatch_control_context():
    signature = inspect.signature(AsyncGenerationRepository.create_or_replay)
    assert "dispatch_control" in signature.parameters


def test_normal_managed_runtime_accepts_dispatch_ledger_and_context():
    signature = inspect.signature(ManagedModelStructuredRuntime.__init__)
    assert "dispatch_ledger" in signature.parameters
    async_signature = inspect.signature(ManagedModelStructuredRuntime.async_design_solutions)
    assert "dispatch_control" in async_signature.parameters


def test_normal_async_solution_service_propagates_dispatch_control():
    signature = inspect.signature(SolutionDesignService.generate_async)
    assert "dispatch_control" in signature.parameters

