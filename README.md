<p align="center">
  <img src="./docs/assets/taotao-mascot.webp" width="128" alt="Taotao, GustoBot's clay-pot assistant">
</p>

<h1 align="center">GustoBot · Taotao</h1>

<p align="center"><strong>Ontology-guided knowledge services</strong><br>Domain semantics · Graph and text evidence · Traceable answers</p>

<p align="center"><strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a></p>

<p align="center">
  <a href="#features">Features</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#documentation">Documentation</a>
</p>

<p align="center">
  <a href="./docs/ONTOLOGY_REUSE.md"><img alt="The default recipe ontology uses OWL and SHACL" src="https://img.shields.io/badge/Ontology-OWL%20%2B%20SHACL-875239"></a>
  <a href="https://www.docker.com/"><img alt="Docker Compose" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&amp;logoColor=white"></a>
  <a href="./LICENSE"><img alt="Apache License 2.0" src="https://img.shields.io/badge/License-Apache%202.0-667866"></a>
</p>

## What is GustoBot?

GustoBot brings domain ontologies, graph facts, and source documents into one question-answering service. The ontology defines concepts, relations, and executable constraints; the graph stores specific facts, while source text preserves their context. The service uses these definitions to plan queries, retrieve evidence, and evaluate results, then cites the sources it actually used.

**Recipes are the current application domain.** Different preparations of the same dish retain their own versions, quantities, steps, and reported durations. Related articles can add background. Domain definitions are configurable; a new domain still needs its own model, field mappings, and query bindings.

## Features

### Ontology-constrained knowledge representation

The default recipe domain uses versioned OWL/RDFS and SHACL definitions for concepts, relations, identity, business properties, units, and evidence shapes. The runtime loads and compiles these definitions so that ingestion and query evaluation share the same domain semantics.

Graph facts retain object relationships and source quotations. Documents preserve context and are published as searchable chunks. Entity links, source identities, and versions connect these forms of evidence, allowing them to support the same answer.

<p align="center">
  <a href="./docs/assets/architecture/knowledge-representation.png">
    <img src="./docs/assets/architecture/knowledge-representation.png" width="800" alt="A domain ontology constrains graph facts, which link to source text and related articles through quotations and entity associations">
  </a>
</p>

Structured records are mapped deterministically and validated before graph ingestion. Documents can be published as text vectors alone. Adding graph facts from a document requires explicit candidate extraction, human review, and validation. [Knowledge representation and ingestion contracts](./docs/DOMAIN_KNOWLEDGE.md)

### Ontology-guided query planning and evaluation

Simple questions follow deterministic paths. For more complex questions, a model selects business properties and conditions allowed by the ontology. The service resolves objects and source versions, then retrieves graph facts, current material, and related articles as needed.

Fact evaluation for formally bound business properties applies supported ontology inference, quantity calculations, and evidence validation. Structured results can be returned directly; when a synthesis is needed, the answer is generated from the retrieved evidence. Ambiguous objects trigger clarification. Unknown values, qualitative quantities, and gaps in the source material remain explicit.

<p align="center">
  <a href="./docs/assets/architecture/knowledge-reasoning.png">
    <img src="./docs/assets/architecture/knowledge-reasoning.png" width="800" alt="A question passes through query planning, joint graph and text retrieval, and rule evaluation to produce results, citations, and evidence gaps">
  </a>
</p>

For example, a sugar quantity can be converted using declared unit rules, while an instruction such as "to taste" stays qualitative. When a particular preparation is selected, its versioned source text governs the recipe; related articles provide background. [Query and evaluation boundaries](./docs/DOMAIN_KNOWLEDGE.md)

### Traceable publication and conversations

The admin interface supports source inspection, document publication and withdrawal, document-record deletion, graph-candidate review, and read-only conversation history. The chat interface shows execution progress and actual citations, retaining the sources and versions used. Knowledge is published through explicit operations; generated answers do not automatically become graph facts. [Admin guide](./docs/ADMIN_GUIDE.md)

## Quick start

Install Docker and Docker Compose, then clone the repository and copy the configuration template.

```bash
git clone https://github.com/skygazer42/GustoBot.git
cd GustoBot
cp .env.example .env
```

In Windows PowerShell, use `Copy-Item .env.example .env` to copy the template. Edit `.env` and replace the placeholders:

- **Chat model:** set `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`.
- **Embedding model:** set `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, and `EMBEDDING_MODEL`. Match `EMBEDDING_DIMENSION` to the model's actual output dimension.
- **Storage:** replace `MYSQL_PASSWORD`, `MYSQL_ROOT_PASSWORD`, and `NEO4J_PASSWORD`. Keep the MySQL application credentials in `DATABASE_URL` consistent with these settings. URL-encode reserved characters in the connection string.
- **Admin login:** set `GUSTOBOT_ADMIN_PASSWORD` and a separate, random `SECRET_KEY` of at least 32 bytes.

Chat and embedding endpoints use OpenAI-compatible APIs and can be configured separately. See the [quick-start guide](./docs/QUICK_START.md) for full configuration, local development, and data-import instructions.

```bash
docker compose --env-file .env up -d --build
```

| Entry point | Default URL |
| --- | --- |
| Recipe interface and Taotao chat | <http://localhost:8000/> |
| Knowledge administration | <http://localhost:8000/admin.html> |
| API documentation | <http://localhost:8000/docs> |
| Health check | <http://localhost:8000/health> |

Ports depend on your configuration. Prepare the recipe catalog and the published knowledge base separately. See [data sources and preparation](./docs/DATA_SOURCES.md) and the [admin guide](./docs/ADMIN_GUIDE.md) for catalog snapshots, images, document publication, and fact ingestion.

## Architecture

Ingestion and question answering share one domain definition. Ingestion publishes graph facts and text chunks through their respective paths. A shared query service plans requests and retrieves evidence, then evaluates rules and produces grounded answers.

<p align="center">
  <a href="./docs/assets/architecture/knowledge-overview.png">
    <img src="./docs/assets/architecture/knowledge-overview.png" width="800" alt="Knowledge ingestion and queries share a domain ontology and semantic runtime, combining graph facts and source text for retrieval and evaluation">
  </a>
</p>

[High-resolution PNG](./docs/assets/architecture/knowledge-overview.png) · [Vector SVG](./docs/assets/architecture/knowledge-overview.svg) · [Chinese version](./README.zh-CN.md#技术架构)

| Responsibility | Current implementation |
| --- | --- |
| Interface and requests | Vue, FastAPI, and AG-UI streaming events; LangGraph adapts ordinary chat to the shared query service |
| Domain semantics and QA | Ontology compilation, business-property bindings, controlled queries, joint retrieval, calculations, and evidence evaluation |
| Knowledge storage | Neo4j for facts and quotations; Milvus for published document vectors |
| Conversations and publication | MySQL for sessions, messages, source versions, ingestion jobs, and publication state |
| Model capabilities | LLMs for explicit candidate extraction, query planning when needed, and grounded expression; embeddings for vectorization |

[Shared query service](./gustobot/application/services/knowledge_query.py) · [Ingestion service](./gustobot/application/services/knowledge_ingestion.py) · [Semantic runtime](./gustobot/infrastructure/knowledge/semantic_runtime.py) · [Diagrams and detailed flows](./docs/ARCHITECTURE.md)

### Domain reuse and supported semantics

The default recipe domain uses the formal OWL/RDFS, OWL-RL, and SHACL execution path. The equipment and generic profiles are YAML contract examples. Adapting a new domain requires configuring and validating its semantics, mappings, and query bindings; some existing evaluation paths remain recipe-specific.

The runtime supports an explicit local ontology fragment and controlled queries. Source quality, entity alignment, and alias decisions still depend on source material and domain review. Inference and evidence validation do not establish the truth of every source document. [Domain profiles](./gustobot/config/domains/) · [Supported semantics](./docs/DOMAIN_KNOWLEDGE.md)

## Documentation

The detailed guides below are currently in Chinese.

- [Quick start](./docs/QUICK_START.md): model configuration, local development, and data import.
- [Domain knowledge service](./docs/DOMAIN_KNOWLEDGE.md): knowledge representation, query plans, evidence, and API contracts.
- [Ontology reuse](./docs/ONTOLOGY_REUSE.md): the Schema.org subset, vocabulary sources, and mapping rationale.
- [Admin guide](./docs/ADMIN_GUIDE.md): document publication, graph review, query testing, and conversation history.
- [Deployment and upgrades](./docs/DEPLOYMENT.md): storage configuration, upgrades, and operations.
- [Code map](./docs/PROJECT_STRUCTURE.md): entry points and module responsibilities.

## Data and license

The project code is licensed under [Apache License 2.0](./LICENSE). Third-party recipes, documents, and images retain their respective licenses. See [data sources and provenance](./docs/DATA_SOURCES.md) for details.

Report issues and suggest improvements through [GitHub Issues](https://github.com/skygazer42/GustoBot/issues).
