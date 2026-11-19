"""Candidate recall is bounded; only authoritative objects can be selected."""

import asyncio
import math
import time
from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import BaseMessage

from gustobot.domain.linking import (
    ENTITY_CATALOG_TYPES,
    CandidateHit,
    GraphRevision,
    IndexPublicationStatus,
    IndexScope,
    LinkedCandidate,
    LinkingContext,
    LinkResolution,
    ObjectReference,
    normalize_name,
)

_EXACT = {"exact", "exact_id", "exactid", "id", "alias", "name"}


class EntityLinkingService:
    def __init__(
        self,
        domain,
        *,
        graph_store,
        candidate_store,
        embedder,
        scopes: dict[str, IndexScope],
        publication_provider,
        mode: Literal["off", "shadow", "on"] = "off",
        concept_top_k: int = 8,
        entity_top_k: int = 10,
        family_limit: int = 20,
        retrieval_deadline: float = 5,
    ):
        if mode not in {"off", "shadow", "on"}:
            raise ValueError("Unknown linking mode")
        if min(concept_top_k, entity_top_k, family_limit, retrieval_deadline) <= 0:
            raise ValueError("Candidate retrieval limits must be positive")
        if domain.semantic_model is None:
            raise ValueError("Entity linking requires a compiled ontology")
        if set(scopes) != {"concept", "entity"}:
            raise ValueError("Concept and entity index scopes are required")
        if any(
            scope.kind != kind
            or scope.domain_id != domain.id
            or scope.ontology_version != domain.version
            for kind, scope in scopes.items()
        ):
            raise ValueError("Candidate scopes must match the current domain")
        self.domain, self.graph = domain, graph_store
        self.store, self.embedder = candidate_store, embedder
        self.scopes, self.publication_provider = scopes, publication_provider
        self.mode = mode
        self.concept_top_k, self.entity_top_k = concept_top_k, entity_top_k
        self.family_limit, self.deadline = family_limit, retrieval_deadline
        self.concepts = tuple(domain.semantic_model.linking_records())

    @staticmethod
    async def _resource(provider):
        return await asyncio.to_thread(provider) if callable(provider) else provider

    @staticmethod
    def _merge(candidates: Sequence[LinkedCandidate]) -> list[LinkedCandidate]:
        records: dict[tuple[str, str], LinkedCandidate] = {}
        for candidate in candidates:
            key = candidate.record.kind, candidate.ref_id
            if key not in records:
                records[key] = candidate.model_copy(deep=True)
                continue
            current = records[key]
            current.match_sources = sorted(set(current.match_sources + candidate.match_sources))
            current.rank_score = max(current.rank_score, candidate.rank_score)
            if candidate.vector_score is not None:
                current.vector_score = candidate.vector_score
                current.generation_id = candidate.generation_id
        return list(records.values())

    @classmethod
    def _fuse(cls, lexical, semantic):
        result = cls._merge([*lexical, *semantic])
        ranks: dict[str, float] = {}
        for sequence in (lexical, semantic):
            for rank, candidate in enumerate(cls._merge(sequence), 1):
                ranks[candidate.record.record_id] = ranks.get(candidate.record.record_id, 0) + 1 / (
                    60 + rank
                )
        for candidate in result:
            candidate.rank_score = ranks[candidate.record.record_id]
        return sorted(
            result,
            key=lambda candidate: (
                not bool(_EXACT.intersection(candidate.match_sources)),
                -candidate.rank_score,
                candidate.record.record_id,
            ),
        )

    def _lexical_concepts(self, question):
        question = normalize_name(question)
        matched = []
        for record in self.concepts:
            terms = [normalize_name(term) for term in [record.label, *record.aliases]]
            lengths = [len(term) for term in terms if term and term in question]
            if lengths:
                matched.append((max(lengths), record))
        matched.sort(key=lambda pair: (-pair[0], pair[1].record_id))
        return [
            LinkedCandidate(record=record, match_sources=["lexical_concept"])
            for _, record in matched[: self.concept_top_k]
        ]

    async def _families(self, graph, candidates):
        semaphore = asyncio.Semaphore(4)

        async def family(candidate):
            async with semaphore:
                result = await graph.lookup_name_family([candidate.ref_id], limit=self.family_limit)
            for item in result.items:
                self.scopes["entity"].validate_record(item.record)
            return result.model_copy(update={"seed_ids": [candidate.ref_id]})

        tasks = [
            asyncio.create_task(family(candidate)) for candidate in self._merge(candidates)[:40]
        ]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    @staticmethod
    def _policy(publication):
        if publication.calibration_id is None:
            return None
        minimum = publication.policy.get("min_cosine")
        margin = publication.policy.get("margin")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (float, int))
            or not math.isfinite(value)
            for value in (minimum, margin)
        ):
            raise ValueError("Calibrated policy requires finite cosine and margin")
        if not -1 <= minimum <= 1 or not 0 <= margin <= 2:
            raise ValueError("Invalid calibrated cosine or margin")
        return {"min_cosine": float(minimum), "margin": float(margin)}

    async def _recall(self, context, usable, expected_types):
        if context.question in context.query_vectors:
            vector = context.query_vectors[context.question]
        else:
            embedder = await self._resource(self.embedder)
            context.provider_calls["candidate_embedding_batches"] = (
                context.provider_calls.get("candidate_embedding_batches", 0) + 1
            )
            vector = await asyncio.to_thread(embedder.embed_query, context.question)
            context.query_vectors[context.question] = vector
        store = await self._resource(self.store)
        jobs = []
        kinds = []
        for kind, publication in usable.items():
            groups: list[tuple[str, ...]] = (
                [()]
                if kind == "concept"
                else [(item,) for item in (expected_types or ENTITY_CATALOG_TYPES)]
            )
            for group in groups:
                jobs.append(
                    asyncio.to_thread(
                        store.search,
                        vector,
                        scope=self.scopes[kind],
                        generation_id=publication.generation_id,
                        expected_types=group,
                        top_k=self.concept_top_k if kind == "concept" else self.entity_top_k,
                    )
                )
                kinds.append(kind)
        tasks = [asyncio.create_task(job) for job in jobs]
        try:
            values = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        result: dict[str, list[CandidateHit]] = {}
        for kind, hits in zip(kinds, values):
            result.setdefault(kind, []).extend(hits)
        return result

    async def _usable_publications(
        self, context: LinkingContext, revision: GraphRevision
    ) -> dict[str, IndexPublicationStatus]:
        publications = await asyncio.gather(
            *(asyncio.to_thread(self.publication_provider, scope) for scope in self.scopes.values())
        )
        usable = {}
        for publication in publications:
            kind = publication.scope.kind
            if publication.scope != self.scopes[kind]:
                raise ValueError("Publication belongs to a different index scope")
            if publication.status != "ready" or publication.generation_id is None:
                context.diagnostics.append(f"{kind} index is {publication.status}")
                continue
            if kind == "entity" and (
                revision.state != "ready" or publication.graph_revision != revision.revision
            ):
                context.status = "stale" if revision.state == "ready" else "uninitialized"
                context.diagnostics.append("Entity index does not match current graph revision")
                continue
            policy = self._policy(publication)
            if policy is None and self.mode == "on":
                context.diagnostics.append(f"{kind} index has no calibrated policy")
                continue
            if policy is not None:
                context.selection_policies[kind] = policy
            usable[kind] = publication
        return usable

    def _filter_recalled_candidates(
        self,
        context: LinkingContext,
        recalled: dict[str, list[CandidateHit]],
        publications: dict[str, IndexPublicationStatus],
    ) -> tuple[list[LinkedCandidate], dict[str, CandidateHit]]:
        concepts = []
        entity_hits: dict[str, CandidateHit] = {}
        catalog = {record.ref_id: record for record in self.concepts}
        for kind, hits in recalled.items():
            publication = publications[kind]
            assert publication.generation_id is not None
            context.generations[kind] = publication.generation_id
            minimum = context.selection_policies.get(kind, {}).get("min_cosine", -1.0)
            for raw_hit in hits:
                hit = CandidateHit.model_validate(raw_hit.model_dump())
                if hit.scope != self.scopes[kind] or hit.generation_id != publication.generation_id:
                    raise ValueError("Search returned an out-of-scope candidate")
                if hit.vector_score < minimum:
                    continue
                if kind == "concept":
                    record = catalog.get(hit.ref_id)
                    if record is not None and record.record_hash == hit.record.record_hash:
                        concepts.append(
                            LinkedCandidate(
                                record=record,
                                match_sources=["vector"],
                                vector_score=hit.vector_score,
                                generation_id=hit.generation_id,
                            )
                        )
                elif (
                    hit.ref_id not in entity_hits
                    or entity_hits[hit.ref_id].vector_score < hit.vector_score
                ):
                    entity_hits[hit.ref_id] = hit
        return concepts, entity_hits

    async def _hydrate_entities(
        self,
        graph,
        hits: dict[str, CandidateHit],
        expected_types: Sequence[str],
        diagnostics: list[str],
    ) -> list[LinkedCandidate]:
        if not hits:
            return []
        ranked_hits = sorted(
            hits.values(), key=lambda hit: (-hit.vector_score, hit.record.record_id)
        )
        semantic_entities = []
        for candidate in await graph.hydrate_candidates([hit.ref_id for hit in ranked_hits[:40]]):
            hit = hits.get(candidate.ref_id)
            if hit is None or candidate.record.record_hash != hit.record.record_hash:
                diagnostics.append("Rejected stale candidate content")
                continue
            if expected_types and candidate.record.object_type not in expected_types:
                raise ValueError("Hydration returned an incompatible object type")
            semantic_entities.append(
                candidate.model_copy(
                    update={
                        "match_sources": [*candidate.match_sources, "vector"],
                        "vector_score": hit.vector_score,
                        "generation_id": hit.generation_id,
                    }
                )
            )
        semantic_entities.sort(key=lambda item: (-self._vector_score(item), item.record.record_id))
        return semantic_entities

    async def _rank_and_expand_candidates(
        self, graph, context: LinkingContext, lexical, semantic_entities, semantic_concepts
    ) -> None:
        context.entities = self._fuse(lexical, semantic_entities)[:40]
        context.concepts = self._fuse(context.concepts, semantic_concepts)[: self.concept_top_k]
        known = {seed for family in context.families for seed in family.seed_ids}
        context.families.extend(
            await self._families(
                graph, [item for item in context.entities if item.ref_id not in known]
            )
        )
        context.entities = self._merge(
            [*context.entities, *(item for family in context.families for item in family.items)]
        )

    async def _prepare_attempt(self, context, expected_types, *, lexical=None):
        started = time.monotonic()
        lexical_concepts = self._lexical_concepts(context.question)
        context.concepts = lexical_concepts
        if self.mode == "off":
            return
        graph = await self._resource(self.graph)
        revision = await graph.graph_revision()
        context.graph_revision = revision
        scope = self.scopes["entity"]
        if (revision.domain_id, revision.ontology_version, revision.ontology_fingerprint) != (
            scope.domain_id,
            scope.ontology_version,
            scope.ontology_fingerprint,
        ):
            raise ValueError("Graph revision belongs to a different ontology scope")
        if lexical is None:
            lexical = await graph.lexical_candidates(
                context.question, expected_types=expected_types, limit=40
            )
        for candidate in lexical:
            scope.validate_record(candidate.record)
        context.families = await self._families(graph, lexical)
        context.entities = self._merge(
            [*lexical, *(item for family in context.families for item in family.items)]
        )
        if any(_EXACT.intersection(item.match_sources) for item in lexical):
            if await graph.graph_revision() != revision:
                context.entities = []
                context.status = "stale"
                context.diagnostics.append("Graph changed while linking candidates")
            return
        publications = await self._usable_publications(context, revision)
        if not publications:
            if context.status == "ready":
                context.status = "degraded" if lexical else "unavailable"
            return
        remaining = self.deadline - (time.monotonic() - started)
        try:
            if remaining <= 0:
                raise TimeoutError("Candidate retrieval deadline exceeded")
            recalled = await asyncio.wait_for(
                self._recall(context, publications, expected_types), timeout=remaining
            )
        except asyncio.CancelledError:
            raise
        # This optional provider boundary reports errors as unavailable, not missing facts.
        except Exception as error:  # noqa: BLE001
            context.status = "degraded" if lexical else "unavailable"
            context.diagnostics.append(f"Candidate recall failed: {type(error).__name__}")
            return
        concepts, entity_hits = self._filter_recalled_candidates(context, recalled, publications)
        semantic_entities = await self._hydrate_entities(
            graph, entity_hits, expected_types, context.diagnostics
        )
        await self._rank_and_expand_candidates(graph, context, lexical, semantic_entities, concepts)
        if await graph.graph_revision() != revision:
            context.entities = lexical
            context.status = "stale"
            context.diagnostics.append("Graph changed while linking candidates")
        if self.mode == "shadow":
            context.timings["shadow_entity_candidates"] = float(len(context.entities))
            context.timings["shadow_concept_candidates"] = float(len(context.concepts))
            context.entities, context.concepts = lexical, lexical_concepts
            context.families = []
        elif not context.entities and context.status == "ready":
            context.status = "no_candidates"

    async def prepare(
        self, question: str, *, history: Sequence[BaseMessage], expected_types: Sequence[str] = ()
    ) -> LinkingContext:
        if not question.strip():
            raise ValueError("Candidate retrieval requires a question")
        if set(expected_types) - set(ENTITY_CATALOG_TYPES):
            raise ValueError("Unsupported candidate entity type")
        started = time.monotonic()
        context = LinkingContext(
            question=question,
            mode=self.mode,
            reference_text="\n".join(str(message.content) for message in history[-4:]),
        )
        await self._attempt_with_budget(context, expected_types, self.deadline)
        if "Graph changed while linking candidates" in context.diagnostics:
            retry = LinkingContext(
                question=question,
                mode=self.mode,
                reference_text=context.reference_text,
                query_vectors=context.query_vectors,
                provider_calls=dict(context.provider_calls),
            )
            await self._attempt_with_budget(
                retry, expected_types, self.deadline - (time.monotonic() - started)
            )
            context = retry
            context.timings["revision_retries"] = 1.0
        context.timings["total_ms"] = (time.monotonic() - started) * 1000
        return context

    async def _attempt_with_budget(self, context, expected_types, seconds, *, lexical=None):
        try:
            await asyncio.wait_for(
                self._prepare_attempt(context, expected_types, lexical=lexical),
                timeout=max(0.0, seconds),
            )
        except asyncio.TimeoutError:
            context.entities = []
            context.families = []
            context.status = "unavailable"
            context.diagnostics.append("Candidate retrieval deadline exceeded")

    async def _refresh_for_resolution(self, context, expected_types):
        if context.graph_revision is None or self.mode == "off":
            return
        graph = await self._resource(self.graph)
        if await graph.graph_revision() == context.graph_revision:
            return
        if context.timings.get("revision_retries", 0) >= 1:
            context.status = "stale"
            context.entities = []
            context.families = []
            context.diagnostics.append("Graph revision changed again before query execution")
            return
        started = time.monotonic()
        elapsed = context.timings.get("total_ms", 0)
        fresh = LinkingContext(
            question=context.question,
            mode=self.mode,
            query_vectors=context.query_vectors,
            provider_calls=dict(context.provider_calls),
            reference_text=context.reference_text,
            verified_ids=context.verified_ids,
        )
        await self._attempt_with_budget(fresh, expected_types, self.deadline - elapsed / 1000)
        for name in type(fresh).model_fields:
            setattr(context, name, getattr(fresh, name))
        context.timings["revision_retries"] = 1.0
        context.timings["total_ms"] = elapsed + (time.monotonic() - started) * 1000

    async def supplement(
        self, references: Sequence[ObjectReference], *, context: LinkingContext
    ) -> LinkingContext:
        started = time.monotonic()
        remaining = self.deadline - context.timings.get("total_ms", 0) / 1000
        try:
            return await asyncio.wait_for(
                self._supplement(references, context=context), timeout=max(0.0, remaining)
            )
        except asyncio.TimeoutError:
            context.status = "unavailable"
            context.diagnostics.append("Post-plan candidate deadline exceeded")
            for reference in references:
                context.mention_candidates.setdefault(self._reference_key(reference), [])
            return context
        finally:
            context.timings["total_ms"] = (
                context.timings.get("total_ms", 0) + (time.monotonic() - started) * 1000
            )

    async def _find_missing_references(
        self, references: Sequence[ObjectReference], *, context: LinkingContext
    ) -> dict[str, ObjectReference]:
        missing = {}
        graph = None
        for reference in references:
            key = self._reference_key(reference)
            pool = [
                item
                for item in context.entities
                if reference.expected_type is None
                or item.record.object_type == reference.expected_type
            ]
            if key in context.mention_candidates or self._named(reference.mention, pool):
                continue
            same_type = sum(item.expected_type == reference.expected_type for item in references)
            if (
                same_type == 1
                and reference.ref_id is not None
                and reference.ref_id in {item.ref_id for item in pool}
            ):
                graph = await self._resource(self.graph) if graph is None else graph
                lexical = await graph.lexical_candidates(
                    reference.mention,
                    expected_types=(
                        [reference.expected_type] if reference.expected_type is not None else []
                    ),
                    limit=40,
                )
                exact = [item for item in lexical if _EXACT.intersection(item.match_sources)]
                if exact:
                    context.entities = self._merge([*context.entities, *exact])
                    context.mention_candidates[key] = [item.ref_id for item in exact]
                    context.families.extend(await self._families(graph, exact))
                continue
            missing[key] = reference
        return missing

    async def _embed_supplement_mentions(
        self, mentions: Sequence[LinkingContext], context: LinkingContext
    ) -> bool:
        if not mentions:
            return True
        if context.provider_calls.get("candidate_embedding_batches", 0) >= 2:
            context.diagnostics.append("Candidate embedding batch limit reached")
            return False
        embedder = await self._resource(self.embedder)
        context.provider_calls["candidate_embedding_batches"] = (
            context.provider_calls.get("candidate_embedding_batches", 0) + 1
        )
        try:
            vectors = await asyncio.to_thread(
                embedder.embed_documents, [mention.question for mention in mentions]
            )
        except asyncio.CancelledError:
            raise
        # This optional provider boundary preserves an explicit degraded state.
        except Exception as error:  # noqa: BLE001
            context.status = "degraded" if context.entities else "unavailable"
            context.diagnostics.append(
                f"Post-plan candidate embedding failed: {type(error).__name__}"
            )
            return False
        if len(vectors) != len(mentions):
            raise ValueError("Post-plan embedding count mismatch")
        for mention, vector in zip(mentions, vectors):
            mention.query_vectors[mention.question] = vector
        return True

    async def _supplement(
        self, references: Sequence[ObjectReference], *, context: LinkingContext
    ) -> LinkingContext:
        missing = await self._find_missing_references(references, context=context)
        if not missing or self.mode != "on":
            return context
        for key in missing:
            context.mention_candidates[key] = []
        if len(missing) > 8 or context.timings.get("supplement_attempts", 0):
            context.diagnostics.append("Post-plan candidate batch limit reached")
            return context
        context.timings["supplement_attempts"] = 1.0
        started = time.monotonic()
        graph = await self._resource(self.graph)
        parts = []
        for key, reference in missing.items():
            mention = reference.mention
            expected = [reference.expected_type] if reference.expected_type is not None else []
            if set(expected) - set(ENTITY_CATALOG_TYPES):
                raise ValueError("Unsupported candidate entity type")
            lexical = await graph.lexical_candidates(mention, expected_types=expected, limit=40)
            part = LinkingContext(
                question=mention, mode=self.mode, reference_text=context.reference_text
            )
            parts.append((key, part, expected, lexical))
        fuzzy = [
            part
            for _, part, _, lexical in parts
            if not any(_EXACT.intersection(item.match_sources) for item in lexical)
        ]
        if not await self._embed_supplement_mentions(fuzzy, context):
            return context
        for key, part, expected, lexical in parts:
            await self._prepare_attempt(part, expected, lexical=lexical)
            if part.status in {"unavailable", "stale", "uninitialized", "degraded"}:
                context.status = "degraded" if context.entities else part.status
            context.entities = self._merge([*context.entities, *part.entities])[:40]
            context.concepts = self._merge([*context.concepts, *part.concepts])[
                : self.concept_top_k
            ]
            context.families.extend(part.families)
            context.generations.update(part.generations)
            context.query_vectors.update(part.query_vectors)
            context.selection_policies.update(part.selection_policies)
            context.mention_candidates[key] = [item.ref_id for item in part.entities]
            context.diagnostics.extend(part.diagnostics)
        context.timings["supplement_ms"] = (time.monotonic() - started) * 1000
        return context

    @staticmethod
    def _reference_key(reference: ObjectReference) -> str:
        return f"{reference.expected_type}:{normalize_name(reference.mention)}"

    @staticmethod
    def _named(mention: str, candidates: Sequence[LinkedCandidate]) -> list[LinkedCandidate]:
        return [
            item
            for item in candidates
            if mention == item.ref_id
            or normalize_name(mention)
            in {normalize_name(name) for name in [item.record.label, *item.record.aliases]}
        ]

    @staticmethod
    def _vector_score(candidate: LinkedCandidate) -> float:
        assert candidate.vector_score is not None
        return candidate.vector_score

    def _candidates_for_reference(
        self, reference: ObjectReference, context: LinkingContext
    ) -> list[LinkedCandidate]:
        pool = [
            item
            for item in context.entities
            if reference.expected_type is None or item.record.object_type == reference.expected_type
        ]
        key = self._reference_key(reference)
        if key in context.mention_candidates:
            allowed = context.mention_candidates[key]
            pool = [item for item in pool if item.ref_id in allowed]
        named = self._named(reference.mention, pool)
        mentioned = normalize_name(reference.mention) in normalize_name(
            context.question + "\n" + context.reference_text
        )
        if reference.ref_id is not None:
            if not (
                mentioned
                or reference.ref_id in context.question
                or reference.ref_id in context.verified_ids
            ):
                return []
            return [item for item in (named or pool) if item.ref_id == reference.ref_id]
        if named:
            return named
        if not mentioned:
            return []
        candidates = sorted(
            [item for item in pool if item.vector_score is not None],
            key=lambda item: -self._vector_score(item),
        )
        margin = context.selection_policies.get("entity", {}).get("margin")
        if margin is None:
            return []
        if (
            len(candidates) > 1
            and self._vector_score(candidates[0]) - self._vector_score(candidates[1]) >= margin
        ):
            return candidates[:1]
        return candidates

    def _apply_name_families(
        self,
        reference: ObjectReference,
        candidates: list[LinkedCandidate],
        context: LinkingContext,
    ) -> tuple[list[LinkedCandidate], bool]:
        ids = {item.ref_id for item in candidates}
        ambiguous = False
        for family in context.families:
            family_ids = {item.ref_id for item in family.items} | set(family.seed_ids)
            if not ids.intersection(family_ids):
                continue
            explicit = [
                item
                for item in family.items
                if item.ref_id in context.question or item.ref_id in context.verified_ids
            ]
            uniquely_named = self._named(reference.mention, family.items)
            if len(explicit) == 1:
                candidates = explicit
            elif len(uniquely_named) == 1 and not family.has_more:
                candidates = uniquely_named
            elif family.has_more or len(family.items) > 1:
                candidates = family.items
                ambiguous = True
        return candidates, ambiguous

    async def resolve(
        self, references: Sequence[ObjectReference], *, context: LinkingContext
    ) -> LinkResolution:
        await self._refresh_for_resolution(
            context,
            list(
                dict.fromkeys(
                    ref.expected_type for ref in references if ref.expected_type is not None
                )
            ),
        )
        selected, bound = [], []
        ambiguous = False
        for reference in references:
            candidates = self._candidates_for_reference(reference, context)
            candidates, family_ambiguous = self._apply_name_families(reference, candidates, context)
            ambiguous |= family_ambiguous
            if len(candidates) == 1 and not ambiguous:
                bound.append(reference.model_copy(update={"ref_id": candidates[0].ref_id}))
            else:
                bound.append(reference.model_copy(update={"ref_id": None}))
            selected.extend(candidates)
            ambiguous |= len(candidates) > 1
        complete = len(bound) == len(references) and all(
            reference.ref_id is not None for reference in bound
        )
        status: Literal["resolved", "clarify", "unavailable", "no_candidates"]
        if complete and selected and not ambiguous:
            status = "resolved"
        elif selected:
            status = "clarify"
        elif context.status in {"unavailable", "stale", "uninitialized", "degraded"}:
            status = "unavailable"
        else:
            status = "no_candidates"
        return LinkResolution(
            references=bound,
            candidates=self._merge(selected),
            status=status,
            diagnostics=list(context.diagnostics),
        )
