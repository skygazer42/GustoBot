"""Read-only evaluation runtime with an optional scoped candidate-policy overlay."""


def create_runtime(*, scope, linking_mode, candidate_calibration=None):
    from scripts.evaluate_knowledge import create_runtime as application_runtime

    base = application_runtime(scope=scope, linking_mode=linking_mode)
    if candidate_calibration is None:
        return base
    if linking_mode != "on" or base.linker is None:
        raise ValueError("Candidate calibration overlay requires an explicit on evaluation runtime")
    from gustobot.application.services.entity_linking import EntityLinkingService
    from gustobot.application.services.knowledge_query import KnowledgeQueryService
    from gustobot.domain.linking import IndexScope

    calibrated_scope = IndexScope.model_validate(candidate_calibration["scope"])
    if base.linker.scopes[calibrated_scope.kind] != calibrated_scope:
        raise ValueError("Candidate calibration overlay scope differs from the runtime")
    original = base.linker

    def publication(selected_scope):
        result = original.publication_provider(selected_scope)
        if selected_scope != calibrated_scope:
            return result
        if (
            result.status != "ready"
            or result.generation_id != candidate_calibration["generation_id"]
            or result.graph_revision != candidate_calibration["graph_revision"]
        ):
            raise ValueError("Candidate calibration overlay generation or graph revision is stale")
        return result.model_copy(
            update={
                "calibration_id": candidate_calibration["calibration_id"],
                "policy": candidate_calibration["policy"],
            }
        )

    isolated_linker = EntityLinkingService(
        original.domain,
        graph_store=original.graph,
        candidate_store=original.store,
        embedder=original.embedder,
        scopes=original.scopes,
        publication_provider=publication,
        mode="on",
        concept_top_k=original.concept_top_k,
        entity_top_k=original.entity_top_k,
        family_limit=original.family_limit,
        retrieval_deadline=original.deadline,
    )
    base.query_service = KnowledgeQueryService(
        base.query_service.domain,
        graph_store=base.query_service.graph,
        documents=base.query_service.documents,
        model=base.query_service.model,
        linker=isolated_linker,
        telemetry_instrumented=base.query_service.telemetry_instrumented,
    )
    base.linker = isolated_linker
    base.deployment = base.deployment | {
        "calibration_id": candidate_calibration["calibration_id"],
        "candidate_policy": candidate_calibration["policy"],
        "policy_scope": "evaluation_process_only; publication metadata is unchanged",
    }
    return base
