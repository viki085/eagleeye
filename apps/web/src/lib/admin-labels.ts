/** Platform terminology for the orchestrator's routes and pipeline steps. */

const ROUTES: Record<string, string> = {
  supervisor: "Agentic orchestration",
  rag: "Retrieval-augmented generation (RAG)",
  rag_auto: "RAG (auto-scoped)",
  sql: "Text-to-SQL",
  simple: "Direct LLM response",
  blocked: "Guardrail intercept",
  unknown: "Unclassified",
};

const STEPS: Record<string, string> = {
  "guard:safety & intent": "Guardrail & intent classification",
  "llm:plan & answer": "LLM planning & synthesis",
  "llm:answer": "LLM response generation",
  "llm:write SQL": "SQL generation (LLM)",
  "llm:write analysis code": "Analysis code generation (LLM)",
  "llm:final answer (limit reached)": "Final synthesis (step limit reached)",
  "tool:query_database": "Text-to-SQL agent (end-to-end)",
  "tool:analyze_data": "Analysis agent (end-to-end)",
  "tool:search_knowledge": "Knowledge-base retrieval",
  "retrieval:search documents": "Document retrieval",
  "retrieval:find tables": "Schema retrieval",
  "retrieval:load inputs": "Dataset loading",
  "tool:run SQL": "SQL execution",
  "tool:run in sandbox": "Sandbox execution",
  "tool:make_chart": "Chart rendering",
  "tool:get_dataset_profile": "Dataset profile lookup",
  "tool:list_data_sources": "Data-source catalog lookup",
  "tool:list_datasets": "Dataset catalog lookup",
  "tool:list_documents": "Document catalog lookup",
  "check:check code": "Code safety check",
  "check:validate SQL": "SQL validation",
  "check:figures": "Figure verification",
  "check:citations": "Citation verification",
  "check:output filter": "Output filtering",
};

export function routeLabel(route: string): string {
  return ROUTES[route] ?? route;
}

export function stepLabel(kind: string, name: string): string {
  return STEPS[`${kind}:${name}`] ?? name.replace(/_/g, " ");
}
