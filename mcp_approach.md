# The MCP-Driven Code Reviewer Approach

This document outlines the architectural evolution of the AI-Powered Code Reviewer. It contrasts the initial **Monolithic Approach** (Phase 1) with the current **MCP (Model Context Protocol) Approach** (Phase 3), which are now successfully merged into this repository.

---

## 1. What We Are Doing

We have migrated the application from a traditional "god class" architecture to an **Agentic Boundary Architecture** using the Model Context Protocol (MCP) and a **Queue-Based Worker Pool**.

### What Do We Have Now?
Previously, the system consisted of only a Webhook router that immediately spawned a background task. Now, the system has four distinct components:
1. **Webhook Handler**: Instantly accepts GitHub payloads and calculates their priority.
2. **Priority Queue**: An in-memory queue that sorts incoming PRs by size (smallest PRs get processed first).
3. **Worker Pool**: A bounded set of concurrent processors (e.g., exactly 2 workers) that pull from the queue, preventing your GPU from crashing under heavy load.
4. **MCP Server Boundary**: An isolated subprocess that strictly handles GitHub API requests securely.

## 2. How We Are Doing It

- **FastMCP Subprocess**: When a webhook arrives, the orchestrator spawns the `github_mcp_server` as a local Python subprocess.
- **Transport via Stdio**: The orchestrator communicates with the MCP server purely over standard input/output (stdio), meaning the MCP server does not need to expose any web ports.
- **Strict Tooling**: The MCP server exposes exactly 4 tools: `get_pr_files`, `check_pr_sha`, `post_review_comment`, and `post_issue_comment`. The orchestrator *cannot* perform any action outside of these 4 tools.
- **Scoped Credentials**: The orchestrator generates a short-lived GitHub token dynamically and passes it into the MCP subprocess's environment variables, hardcoding it to a single specific repository (`SCOPED_REPO`). The MCP server rejects any tool call that attempts to access a different repository.

---

## 3. Comparing the Approaches

### Monolithic Approach (The Previous POC)
In the monolithic design, `review_service.py` handled webhook parsing, database state, AI prompting, LLM parsing, and `httpx` GitHub API calls all in one place.

#### Pros:
- **Simplicity & Setup**: Extremely fast to build. Only requires one file and one standard HTTP client.
- **Low Overhead**: No subprocess management or inter-process communication serialization overhead.

#### Cons:
- **Zero Security Boundaries**: If the AI logic were upgraded to a dynamic agent loop, a hallucinating LLM would have unrestricted access to the GitHub token and could theoretically delete repositories or leak code.
- **Tangled Codebase**: Network retries, API pagination, and LLM logic are intertwined, making it hard to maintain or swap out the AI model logic without breaking the GitHub integration.

### MCP Approach (The Current System)
The merged architecture strictly isolates the AI intelligence from the GitHub execution environment.

#### Pros:
- **Airtight Data Privacy & Security**: The AI logic no longer has internet access. It can only execute the 5 tools provided by the MCP server. Even a fully autonomous, multi-turn AI agent cannot exploit the system beyond those boundaries.
- **Token Isolation**: The token injected into the MCP server is scoped exclusively to the exact repository the PR belongs to, guaranteeing zero cross-contamination in a multi-tenant or multi-repo organization.
- **Future-Proofing for Agents**: Because the GitHub API is now wrapped in standard MCP tools, you can easily plug this server into any MCP-compatible framework (like LangChain, LlamaIndex, or raw Claude/OpenAI tool-calling loops) with zero code changes.

#### Cons:
- **Setup Complexity**: Requires the `mcp` SDK, subprocess lifecycle management (`asynccontextmanager`), and careful JSON serialization between the client and server.
- **Slight Latency**: Serializing data to pass over `stdio` introduces a negligible (but mathematically present) latency penalty compared to in-memory function calls.

---

## 4. Cost, Scale, and Effort Analysis

For an internal, on-premise organization aiming to handle multiple simultaneous PR requests across various developers:

- **Cost**: Both approaches cost $0 in API fees since you are running an on-prem local LLM (`Ollama`). The infrastructure cost is identical (your local GPU/compute).
- **Setup**: The MCP approach took more effort to set up initially (Phase 3). However, because the tools are now abstracted, maintaining it requires *less* effort going forward. You can update the LLM prompts or switch from Ollama to vLLM without touching the GitHub API code.
- **Is it worth it?** **Yes.** By merging the MCP boundary with the **Priority Queue Worker Pool** (Phase 2), the system is now enterprise-grade. It can safely ingest 100 simultaneous webhooks, queue them by size, process them synchronously without crashing your GPU, and post the results securely through the sandboxed MCP server.

---
