"""Component factory and dependency injection for CLAW.

ClawFactory.create() builds the full dependency graph and returns
a ClawContext dataclass with all wired components.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from claw.core.config import ClawConfig, load_config
from claw.core.models import AgentMode
from claw.db.engine import DatabaseEngine
from claw.db.embeddings import EmbeddingEngine
from claw.db.repository import Repository
from claw.llm.client import LLMClient
from claw.llm.token_tracker import TokenTracker
from claw.security.policy import AutonomyLevel, SecurityPolicy
from claw.agents.interface import AgentInterface

logger = logging.getLogger("claw.factory")


@dataclass
class ClawContext:
    """All wired components for a CLAW session."""
    config: ClawConfig
    engine: DatabaseEngine
    repository: Repository
    embeddings: EmbeddingEngine
    llm_client: LLMClient
    token_tracker: TokenTracker
    security: SecurityPolicy
    agents: dict[str, AgentInterface] = field(default_factory=dict)
    prism_engine: Any = None
    dispatcher: Any = None
    verifier: Any = None
    budget_enforcer: Any = None
    degradation_manager: Any = None
    health_monitor: Any = None
    error_kb: Any = None
    semantic_memory: Any = None
    prompt_evolver: Any = None
    pattern_learner: Any = None
    miner: Any = None
    governance: Any = None
    self_consumer: Any = None
    assimilation_engine: Any = None

    async def close(self) -> None:
        """Cleanly shut down all components."""
        await self.llm_client.close()
        await self.engine.close()
        logger.info("ClawContext closed")


class ClawFactory:
    """Builds the complete CLAW dependency graph."""

    @staticmethod
    async def create(
        config_path: Optional[Path] = None,
        workspace_dir: Optional[Path] = None,
    ) -> ClawContext:
        """Create a fully wired ClawContext.

        Args:
            config_path: Path to claw.toml. Defaults to ./claw.toml.
            workspace_dir: Working directory for agent operations.
        """
        config = load_config(config_path)

        # Database
        engine = DatabaseEngine(config.database)
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()

        # Embeddings
        embeddings = EmbeddingEngine(config.embeddings)

        # Seed knowledge — auto-import on first run (after schema + embeddings)
        try:
            from claw.community.seeder import run_seed
            seed_summary = await run_seed(
                engine=engine,
                embedding_engine=embeddings,
                config=config,
            )
            if seed_summary.get("imported", 0) > 0:
                logger.info(
                    "Seed knowledge loaded: %d methodologies imported",
                    seed_summary["imported"],
                )
        except Exception as e:
            logger.warning("Seed knowledge loading failed (non-fatal): %s", e)

        repository = Repository(engine)

        # PRISM multi-scale embeddings
        from claw.embeddings.prism import PrismEngine
        prism_engine = PrismEngine(embedding_engine=embeddings)

        # LLM client
        llm_client = LLMClient(config.llm)

        # Token tracker
        token_tracker = TokenTracker(
            repository=repository,
            jsonl_path=config.token_tracking.jsonl_path if config.token_tracking.enabled else None,
            cost_per_1k_input=config.token_tracking.cost_per_1k_input,
            cost_per_1k_output=config.token_tracking.cost_per_1k_output,
        )

        # Security
        ws = workspace_dir or Path(".").resolve()
        autonomy = AutonomyLevel.SUPERVISED
        sec_cfg = config.security
        if sec_cfg.autonomy_level.upper() == "FULL":
            autonomy = AutonomyLevel.FULL
        elif sec_cfg.autonomy_level.upper() == "READ_ONLY":
            autonomy = AutonomyLevel.READ_ONLY

        security = SecurityPolicy(
            autonomy=autonomy,
            workspace_dir=ws,
            allowed_commands=sec_cfg.allowed_commands,
            forbidden_paths=sec_cfg.forbidden_paths,
            max_actions_per_hour=sec_cfg.rate_limit_per_hour,
            safe_env_vars=sec_cfg.safe_env_vars,
        )

        # Agents
        agents: dict[str, AgentInterface] = {}
        for agent_name, agent_cfg in config.agents.items():
            if not agent_cfg.enabled:
                continue
            agent = _create_agent(agent_name, agent_cfg, workspace_dir=str(ws))
            if agent:
                agents[agent_name] = agent

        # CAG corpus loading — inject into all agents if enabled
        cag_loaded = False
        cag_retriever = None
        if config.cag.enabled:
            from claw.memory.cag_retriever import CAGRetriever
            cag_retriever = CAGRetriever(config.cag)
            cag_loaded = await cag_retriever.load_cache(
                config.instances.instance_name if hasattr(config, "instances") else "general"
            )
            if cag_loaded:
                corpus = cag_retriever.get_corpus(
                    config.instances.instance_name if hasattr(config, "instances") else "general"
                )
                budget = config.cag.knowledge_budget_chars
                for agent in agents.values():
                    agent.set_cag_corpus(corpus, knowledge_budget_chars=budget)
                logger.info(
                    "CAG corpus loaded into %d agents (budget=%d chars)",
                    len(agents), budget,
                )

        # Token budget — derive from local model ctx_size or CAG config
        # Priority: local agent config ctx_size (if a "local" agent is enabled)
        #           > cag.token_budget_max (when CAG is enabled)
        #           > default 100_000
        local_agent_cfg = config.agents.get("local")
        if local_agent_cfg and local_agent_cfg.enabled and local_agent_cfg.mode == "local":
            # LocalLLMConfig.ctx_size is not on AgentConfig, but the
            # orchestrator.max_tokens_per_task mirrors the intent. For local
            # models the practical budget is the model's context window, which
            # the user sets via cag.token_budget_max or orchestrator settings.
            token_budget = config.cag.token_budget_max
        elif config.cag.enabled:
            token_budget = config.cag.token_budget_max
        else:
            token_budget = 100_000

        for agent in agents.values():
            agent.set_token_budget(token_budget)

        if token_budget != 100_000:
            logger.info(
                "Token budget set to %d for %d agents",
                token_budget, len(agents),
            )

        # KV cache manager — enable prefix caching for local agents
        # when CAG is loaded and a local agent is configured.
        # Tier 1: TurboQuant (turboq) — ~4.9x compression, near-lossless
        # Tier 2: Ollama 0.19 MLX — 2x (q8_0) or 4x (q4_0) compression
        # Both tiers use the same stable system message prefix strategy.
        if config.cag.enabled and local_agent_cfg and local_agent_cfg.enabled:
            from claw.memory.kv_cache_manager import KVCacheManager
            local_llm_cfg = config.local_llm if hasattr(config, "local_llm") else None
            keep_alive = local_llm_cfg.keep_alive if local_llm_cfg else -1
            kv_quant = local_llm_cfg.kv_cache_quantization if local_llm_cfg else "q8_0"
            provider = local_llm_cfg.provider if local_llm_cfg else "ollama"
            kv_mgr = KVCacheManager(
                keep_alive=keep_alive,
                kv_cache_quantization=kv_quant,
                provider=provider,
            )

            # Build the stable system message from the CAG corpus
            corpus_for_kv = ""
            if cag_loaded and cag_retriever is not None:
                ganglion = config.instances.instance_name if hasattr(config, "instances") else "general"
                corpus_for_kv = cag_retriever.get_corpus(ganglion)
            if corpus_for_kv:
                kv_mgr.build_system_message(corpus_for_kv, config.cag.knowledge_budget_chars)
                for agent in agents.values():
                    agent.set_kv_cache_manager(kv_mgr)
                logger.info(
                    "KV cache manager enabled: provider=%s, quant=%s (%.1fx), "
                    "keep_alive=%d, system_msg=%d chars",
                    provider, kv_quant, kv_mgr.compression_ratio,
                    keep_alive, len(kv_mgr.system_message),
                )

        # Dispatcher (with optional Kelly sizer)
        from claw.dispatcher import Dispatcher
        kelly_sizer = None
        if config.kelly.enabled:
            from claw.evolution.kelly import BayesianKellySizer
            kelly_sizer = BayesianKellySizer(
                kappa=config.kelly.kappa,
                f_max=config.kelly.f_max,
                min_exploration_floor=config.kelly.min_exploration_floor,
                payoff_default=config.kelly.payoff_default,
                prior_alpha=config.kelly.prior_alpha,
                prior_beta=config.kelly.prior_beta,
                local_quality_multiplier=config.kelly.local_quality_multiplier,
            )
            logger.info("Kelly sizer enabled: kappa=%.1f, f_max=%.2f", config.kelly.kappa, config.kelly.f_max)
        dispatcher = Dispatcher(
            agents=agents,
            exploration_rate=config.orchestrator.exploration_rate,
            repository=repository,
            kelly_sizer=kelly_sizer,
        )

        # Verifier
        from claw.verifier import Verifier
        verifier = Verifier(
            embedding_engine=embeddings,
            banned_dependencies=getattr(config.sentinel, "banned_dependencies", []) if hasattr(config, "sentinel") else [],
            drift_threshold=getattr(config.sentinel, "drift_threshold", 0.40) if hasattr(config, "sentinel") else 0.40,
            llm_client=llm_client,
            min_test_count=getattr(config.sentinel, "min_test_count", 0) if hasattr(config, "sentinel") else 0,
        )

        # Health Monitor
        from claw.orchestrator.health_monitor import HealthMonitor
        health_monitor = HealthMonitor(
            repository=repository,
            config=config.orchestrator,
        )

        # Budget Enforcer
        from claw.budget import BudgetEnforcer
        budget_enforcer = BudgetEnforcer(
            repository=repository,
            config=config,
        )

        # Degradation Manager
        from claw.degradation import DegradationManager
        degradation_manager = DegradationManager(
            health_monitor=health_monitor,
            dispatcher=dispatcher,
            all_agent_ids=list(agents.keys()) if agents else None,
        )

        # Error KB
        from claw.memory.error_kb import ErrorKB
        error_kb = ErrorKB(repository=repository)

        # Memory Governance
        from claw.memory.governance import MemoryGovernor
        governance = MemoryGovernor(
            repository=repository,
            config=config.governance,
            claw_config=config,
        )

        # Semantic Memory
        from claw.memory.semantic import SemanticMemory
        from claw.memory.hybrid_search import HybridSearch
        hybrid_search = HybridSearch(
            repository=repository,
            embedding_engine=embeddings,
            prism_engine=prism_engine,
            novelty_retrieval_boost=config.assimilation.novelty_retrieval_boost,
            potential_retrieval_boost=config.assimilation.potential_retrieval_boost,
            deep_conf_config=config.deep_conf,
        )
        semantic_memory = SemanticMemory(
            repository=repository,
            embedding_engine=embeddings,
            hybrid_search=hybrid_search,
            prism_engine=prism_engine,
            governance=governance,
        )

        # Prompt Evolver
        from claw.evolution.prompt_evolver import PromptEvolver
        prompt_evolver = PromptEvolver(
            repository=repository,
            semantic_memory=semantic_memory,
            error_kb=error_kb,
            ab_test_kappa=config.evolution.ab_test_kappa,
        )

        # Pattern Learner
        from claw.evolution.pattern_learner import PatternLearner
        pattern_learner = PatternLearner(
            repository=repository,
            semantic_memory=semantic_memory,
        )

        # Repo Miner (assimilation_engine wired after creation below)
        from claw.miner import RepoMiner
        miner = RepoMiner(
            repository=repository,
            llm_client=llm_client,
            semantic_memory=semantic_memory,
            config=config,
            governance=governance,
        )

        # Self-Consumer
        from claw.self_consumer import SelfConsumer
        self_consumer = SelfConsumer(
            repository=repository,
            llm_client=llm_client,
            semantic_memory=semantic_memory,
            config=config,
            governance_config=config.governance,
        )

        # Capability Assimilation Engine
        from claw.evolution.assimilation import CapabilityAssimilationEngine
        assimilation_engine = CapabilityAssimilationEngine(
            repository=repository,
            llm_client=llm_client,
            config=config,
        )

        # Wire assimilation into miner and self-consumer
        miner.assimilation_engine = assimilation_engine
        self_consumer.assimilation_engine = assimilation_engine

        # Run startup governance sweep
        if config.governance.sweep_on_startup:
            try:
                sweep_report = await governance.run_full_sweep()
                logger.info(
                    "Startup governance sweep: gc=%d, culled=%d",
                    sweep_report.dead_collected,
                    sweep_report.quota_culled,
                )
            except Exception as e:
                logger.warning("Startup governance sweep failed: %s", e)

        ctx = ClawContext(
            config=config,
            engine=engine,
            repository=repository,
            embeddings=embeddings,
            llm_client=llm_client,
            token_tracker=token_tracker,
            security=security,
            agents=agents,
            prism_engine=prism_engine,
            dispatcher=dispatcher,
            verifier=verifier,
            budget_enforcer=budget_enforcer,
            degradation_manager=degradation_manager,
            health_monitor=health_monitor,
            error_kb=error_kb,
            semantic_memory=semantic_memory,
            prompt_evolver=prompt_evolver,
            pattern_learner=pattern_learner,
            miner=miner,
            governance=governance,
            self_consumer=self_consumer,
            assimilation_engine=assimilation_engine,
        )

        agent_names = list(agents.keys()) if agents else ["none"]
        logger.info(
            "ClawContext created: db=%s, agents=[%s], evolution=[error_kb, semantic_memory, prompt_evolver, pattern_learner]",
            config.database.db_path,
            ", ".join(agent_names),
        )
        return ctx


def _create_agent(
    name: str,
    agent_cfg: Any,
    workspace_dir: Optional[str] = None,
) -> Optional[AgentInterface]:
    """Create a single agent by name."""
    import os

    mode = AgentMode(agent_cfg.mode)
    api_key = os.getenv(agent_cfg.api_key_env, "") if agent_cfg.api_key_env else ""

    if name == "claude":
        from claw.agents.claude import ClaudeCodeAgent
        return ClaudeCodeAgent(
            mode=mode,
            api_key=api_key,
            model=agent_cfg.model,
            timeout=agent_cfg.timeout,
            max_budget_usd=agent_cfg.max_budget_usd,
            workspace_dir=workspace_dir,
            max_tokens=agent_cfg.max_tokens,
        )

    if name == "codex":
        from claw.agents.codex import CodexAgent
        return CodexAgent(
            mode=mode,
            api_key=api_key,
            model=agent_cfg.model,
            timeout=agent_cfg.timeout,
            max_tokens=agent_cfg.max_tokens,
            workspace_dir=workspace_dir,
        )

    if name == "gemini":
        from claw.agents.gemini import GeminiAgent
        return GeminiAgent(
            mode=mode,
            api_key=api_key,
            model=agent_cfg.model,
            timeout=agent_cfg.timeout,
            workspace_dir=workspace_dir,
            max_tokens=agent_cfg.max_tokens,
        )

    if name == "grok":
        from claw.agents.grok import GrokAgent
        return GrokAgent(
            mode=mode,
            api_key=api_key,
            model=agent_cfg.model,
            timeout=agent_cfg.timeout,
            max_budget_usd=agent_cfg.max_budget_usd,
            workspace_dir=workspace_dir,
            max_tokens=agent_cfg.max_tokens,
        )

    if name == "local":
        from claw.agents.local_agent import LocalAgent
        return LocalAgent(
            model=agent_cfg.model,
            local_base_url=agent_cfg.local_base_url or "http://localhost:11434/v1",
            timeout=agent_cfg.timeout,
            max_tokens=agent_cfg.max_tokens,
            workspace_dir=workspace_dir,
        )

    logger.warning("Unknown agent name: '%s'", name)
    return None
