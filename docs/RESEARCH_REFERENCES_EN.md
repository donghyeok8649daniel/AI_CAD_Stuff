# Research references and reconnect (2.19.0)

Open **GitHub research / Attach files…** in the AI panel, or **File → Research repository / AI references…**.

Enter a github.com repository URL and optional branch/tag. An empty optional reference scope means the **whole repository root**; enter a directory such as `docs`, or an exact file path, to narrow it. Public repositories need no token. For private repositories, use an existing Git credential or a fine-grained token with **Contents: Read** for that repository. The token button opens GitHub's official token settings; a browser sign-in alone does not authenticate CAD.

Connect to automatically add the pinned path index immediately, then bounded excerpts of readable documents. Search works across the full cached path index; only the first 2,000 matching rows are displayed at once, with total/index/matching counts shown separately. Use Ctrl/Shift to select additional exact documents and add them. Adding with no selection refreshes the current scope's automatic overview. Inspect the text, source, commit, content hash and truncation markers before choosing **Use references**. Canceling or closing preserves the parent's existing references and CAD design. If capacity is full, the dialog reports this without discarding your attachments.

Codex, Ollama and OpenAI design/chat receive confirmed attachments. The offline dimension parser does not understand documents. Indexing the entire repository is different from sending every file body: AI receives only the bounded index/excerpts and manually selected document snapshots visible in the preview. The integration only reads GitHub and never uploads files, runs repository code or invokes a research solver.

Files are pinned to the commit at connection time. Reconnect to refresh the automatic index/excerpts while preserving other manual/local attachments. Manually re-added files replace the same repository/path. Only repository address, branch and an explicitly chosen scope are saved. Tokens and attached bodies are session-only, and new/open documents clear attachments and previous chat context. Removing references also clears chat history so old research content is not silently reused.

Local attachments support PDF, TXT, MD, RST, CSV/TSV, JSON, YAML, TOML, XML and text source code. Limit: 4 MB per file, up to 8 references, 60,000 total characters, first 20,000 characters per file. Truncation is visible.

Automatic repository addition uses one path index plus up to two excerpt bundles within those shared limits. It prioritizes README/text documents, reads up to 24 files and 12 MB total, and includes at most 4,000 body characters per document. The reference notes report how many readable candidates were included, skipped or clipped. Manually attach important documents missing from the automatic overview. The transmitted index itself is limited to 20,000 characters, distinct from the full searchable UI metadata.

PDF extraction reads text from up to the first 50 pages, with page provenance, and does not interpret scanned images, drawings or faithfully reconstruct table layouts/equations. No-text PDFs and LFS pointers are rejected. Binary/oversized files, directories, symlinks and submodules appear as metadata-only paths; their bodies are not read or executed. A truncated GitHub recursive tree triggers pinned subtree traversal, bounded by 100,000 paths, 1,024 subtree requests, time and response-size limits. Incomplete discovery or a query failure is reported rather than described as a complete repository read.

## Connection recovery

Transient Codex connection/stream errors enter an automatic waiting state. The app allows server-managed retries; terminal transport failures close the owned session and reconnect approximately every 5, 10, 20, then 30 seconds. Original request, references, completed capability selection and latest validation feedback survive. The interrupted generation stage is resubmitted, not resumed from an exact output token.

Reconnect waiting does not consume the active time limit; generation after reconnect still does. Unlimited mode has no active generation deadline. Cancellation works during waiting. Auth, quota, invalid-request and unknown errors are not retried indefinitely. Retried generation can consume additional subscription allowance. This is in-session recovery, not restart/reboot persistence; paid OpenAI API and Ollama connection policies are unchanged.

## Names, search and notifications

- **F2**, Edit, context menu or the properties button renames a part. If several parts are selected, choose the individual one first. Names support 1–80 characters without changing IDs, geometry, joints or groups; undo/redo and project save/load work.
- **Ctrl+F** searches parts, features, groups, sketches, joints and commands. Use multiple terms, category filter, arrow keys and Enter. Objects are selected; commands execute. Ctrl+K remains available.
- A ready AI design triggers a native notification and taskbar attention. Unverified drafts say review is required; application still needs preview confirmation. Click the notice to return to CAD. **View → AI design completion notifications** controls the preference. Windows notification/focus settings may hide the banner.

References: [GitHub read permissions](https://docs.github.com/en/rest/repos/contents), [Codex app-server errors](https://learn.chatgpt.com/docs/app-server#errors), [PDF text extraction limitations](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
