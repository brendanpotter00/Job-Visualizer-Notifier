"""job-enricher — local Claude-Code job-enrichment workflow.

A laptop-side agent that PULLS unenriched jobs from Job-Visualizer-Notifier
(JVN), cleans + classifies + judges them locally under the Claude Code
subscription (no per-token API cost), and writes the results back to JVN.
See CLAUDE.md and docs/ for the architecture.
"""

__version__ = "0.1.0"
