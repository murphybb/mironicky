"""Research service package."""

from research_layer.services.candidate_confirmation_service import (
    CandidateConfirmationService,
)
from research_layer.services.graph_build_service import GraphBuildService
from research_layer.services.graph_query_service import GraphQueryService
from research_layer.services.hypothesis_service import HypothesisService
from research_layer.services.hypothesis_trigger_detector import HypothesisTriggerDetector
from research_layer.services.llm_gateway import LLMGateway, ResearchLLMError
from research_layer.services.llm_result_parser import LLMParseError, LLMResultParser
from research_layer.services.llm_trace import LLMCallResult
from research_layer.services.failure_impact_service import FailureImpactService
from research_layer.services.package_build_service import PackageBuildService
from research_layer.services.recompute_service import RecomputeService
from research_layer.services.research_llm_dependencies import (
    build_research_llm_gateway,
    get_openai_compatible_client,
)
from research_layer.services.route_generation_service import RouteGenerationService
from research_layer.services.retrieval_views_service import ResearchRetrievalService
from research_layer.services.score_service import ScoreService
from research_layer.services.source_import_service import SourceImportService
from research_layer.services.source_parser import SourceParser
from research_layer.services.version_diff_service import VersionDiffService

__all__ = [
    "SourceImportService",
    "SourceParser",
    "CandidateConfirmationService",
    "GraphBuildService",
    "GraphQueryService",
    "HypothesisService",
    "HypothesisTriggerDetector",
    "LLMGateway",
    "ResearchLLMError",
    "LLMResultParser",
    "LLMParseError",
    "LLMCallResult",
    "get_openai_compatible_client",
    "build_research_llm_gateway",
    "FailureImpactService",
    "PackageBuildService",
    "RecomputeService",
    "RouteGenerationService",
    "ResearchRetrievalService",
    "ScoreService",
    "VersionDiffService",
]
