"""SSE event vocabulary (LLD §2.3). Producers and the web fold must agree on these."""

RUN_STARTED = "run.started"  # {run_id}
GUARD_RESULT = "guard.result"  # {safe, intent, route}
STEP_STARTED = "step.started"  # {step_id, parent_id, kind, name, input_summary}
STEP_FINISHED = "step.finished"  # {step_id, status, output_summary, duration_ms, tokens, cost}
TEXT_DELTA = "text.delta"  # {text}
TEXT_REPLACE = "text.replace"  # {text} — output filter replaced the answer
# {n, document_id, chunk_id, title, page, heading_path, scope, snippet, element_type}
CITATION = "citation"
# {artifact_id, type, title, sql, mode, columns, row_count, truncated, preview}
ARTIFACT = "artifact"
CHART = "chart"  # {chart_id, title, spec (Vega-Lite, data inline), summary, source_id}
# {notebook_id, title, inputs, cells: [{index, purpose, code, status, stdout, error, note,
#   stats, figures, tables}], figure_count, status}
NOTEBOOK = "notebook"
CHAT_UPDATED = "chat.updated"  # {chat_id, title}
RUN_DONE = "run.done"  # {message_id, status, degraded, cancelled, usage}
RUN_ERROR = "run.error"  # {code, user_message}
