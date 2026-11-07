# Source reference index extension

This standalone Python standard-library extension uses Research Partner JSON process protocol 1. It reads only brokered, SHA256-bound JSON exports. Register manifest.json and main.py through Settings → Extensions, then explicitly grant execute_code/read_inputs/write_outputs for that code version. It is trusted local code, not an OS sandbox.

Call export_index with registered input assets and optional params.documents entries containing exact id and revision. Sources must be separate supplied object exports; missing versions stay missing. It never follows network or filesystem references in documents. CSV retains exact UTF-8 text, including commas/newlines/quotes, plus JSON-pointer location and each input hash. Import text columns as text in a spreadsheet. Markdown is a readable companion. Identity/block lookup is not scientific support or review approval.

Source references are explicit source_ref or source_refs fields within content. Only a unique top-level content.blocks id resolves a text snippet; object-only, missing, ambiguous and nontext references are reported separately. No scientific fitting, provider calls or raw-data changes. Permissions reset on upgrade/rollback; uninstall preserves published output assets. No private research inputs are included in this source package.

Version 1.1 adds a typed JSON companion for exact-revision joins, referrer context and source titles in CSV/JSON, and groups the Markdown by titled document with a source-history lookup instruction. Each explicit reference remains a separate row and each resolved source snippet remains complete. The original1.0 outputs are retained as historical artifacts.

Malformed source block collections are retained as invalid_source_blocks for affected references while valid/missing rows still appear. Invalid reference fields are diagnosed before lookup, with raw_reference retained for inspection. This addresses independently observed generic robustness and navigation defects; it does not revise the input science.
