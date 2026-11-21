import type { DomainDefinition, KnowledgeGraph, Relation } from "./contracts";

function constraintRelations(domain: DomainDefinition): Relation[] {
  const relations = new Map<string, Relation>();
  for (const [type, definition] of Object.entries(domain.allowed_edges)) {
    for (const source of definition.domain) {
      for (const target of definition.range) {
        const id = JSON.stringify([type, source, target]);
        relations.set(id, { id, type, source_id: source, target_id: target, properties: {}, evidence: [] });
      }
    }
  }
  return [...relations.values()];
}

/** Return omitted type-to-type constraints so incomplete definitions stay visible. */
export function missingOntologyConstraints(domain: DomainDefinition): Relation[] {
  const types = new Set(Object.keys(domain.classes));
  return constraintRelations(domain).filter((relation) =>
    !types.has(relation.source_id) || !types.has(relation.target_id),
  );
}

/** Project declared types and constraints for display, without creating instance facts. */
export function buildOntologyGraph(domain: DomainDefinition): KnowledgeGraph {
  const entities = Object.entries(domain.classes).map(([symbol, definition]) => ({
    id: symbol, type: symbol, name: definition.label || symbol, aliases: [], properties: {}, evidence: [],
  }));
  const types = new Set(entities.map((entity) => entity.id));
  return {
    entities,
    relations: constraintRelations(domain).filter((relation) =>
      types.has(relation.source_id) && types.has(relation.target_id),
    ),
    sources: [],
  };
}
