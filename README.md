# AI-Powered Code Reviewer POC

This repository contains a Proof of Concept (POC) for an automated, AI-driven GitHub Pull Request code reviewer built with **FastAPI**, **Google Gemini 2.5 Flash Lite**, and the **GitHub API**. 

The goal of this application is to listen to GitHub webhooks whenever a Pull Request is opened or synchronized, extract the unified diff, and use Gemini to perform a production-grade code review. It then posts a structured, actionable review comment back to the GitHub PR.

---

## 🚀 Key Features

### 1. Production-Grade Code Assessment
The AI prompt has been strictly designed to perform high-quality, production-grade Python code reviews. It analyzes the PR diff to identify:
* **Security vulnerabilities and edge cases.**
* **Performance bottlenecks and memory leaks.**
* **Code readability, maintainability, and adherence to SOLID principles.**
* **Potential logic bugs.**

### 2. Structured, Predictable AI Responses
To ensure reliability, we enforce structured JSON output from Gemini. Using the new `google.genai` SDK and **Pydantic** models (`CodeReviewResult` and `CodeReviewComment`), we guarantee that the AI strictly returns specific fields: `file_path`, `line_number`, `issue_type`, `comment`, and `suggestion`.

### 3. Frontend-Friendly PR Comments
Instead of relying on flaky inline diff comments (which often fail if line calculations are slightly off), the bot posts a robust **general PR comment**. 
The comment is formatted in clean Markdown for developers to read on GitHub. **Additionally**, we embed the raw JSON payload inside a hidden HTML comment (`<!-- FE_DATA_START ... FE_DATA_END -->`). This makes it incredibly easy for a custom Frontend UI to parse the comment and render interactive UI components.

### 4. Robust Error Handling & Retries
The application is resilient against upstream API instability. If the Gemini API experiences high demand (`503 UNAVAILABLE`) or rate limiting (`429 TOO MANY REQUESTS`), the application employs an **exponential backoff retry mechanism** to wait and try again. If the API fails completely, the webhook aborts gracefully without crashing the main FastAPI event loop.

### 5. Clean FastAPI Architecture
The codebase follows standard modern FastAPI architectural patterns:
* `main.py`: The lightweight entrypoint for the FastAPI application and webhook routing.
* `models/schemas.py`: Contains the Pydantic data schemas.
* `services/review_service.py`: Contains the core business logic, including GitHub API interactions and Gemini AI processing.

---

## 🛠️ Project Architecture

```
code-reviewer-poc/
├── main.py                  # FastAPI app and webhook router
├── models/
│   ├── __init__.py
│   └── schemas.py           # Pydantic structured output models
├── services/
│   ├── __init__.py
│   └── review_service.py    # GitHub & Gemini integration logic
├── calculator.py            # Example target code for review
└── .env                     # Environment variables (git-ignored)
```

---

## ⚙️ Setup and Installation

### Prerequisites
* Python 3.9+
* A Google Gemini API Key
* A GitHub Personal Access Token (PAT) with `repo` permissions

### 1. Clone and Install Dependencies
```bash
git clone <your-repo-url>
cd code-reviewer-poc
pip install fastapi uvicorn httpx pydantic google-genai python-dotenv PyGithub
```

### 2. Configure Environment Variables
Create a `.env` file in the root directory:
```env
GITHUB_TOKEN=your_github_personal_access_token_here
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Run the Server
Start the local development server:
```bash
uvicorn main:app --reload --port 8000
```

### 4. Connect to GitHub Webhooks
To test locally, use a tool like **Hookdeck** or **ngrok** to expose your local port 8000 to the internet.
```bash
hookdeck listen 8000
```
Then, go to your GitHub Repository Settings -> Webhooks, and add the public URL provided by Hookdeck appended with `/webhook` (e.g., `https://yourendpoint.hookdeck.com/webhook`). Ensure you select **Pull requests** as the trigger event.

---

## 🤖 How It Works (The Lifecycle)

1. **Webhook Trigger**: A developer opens or pushes a commit to a PR. GitHub fires a webhook payload to the `/webhook` endpoint.
2. **Diff Extraction**: The `review_service` fetches the raw unified diff of the PR using the GitHub REST API.
3. **Duplicate Check**: The bot scans the PR's existing comments to ensure it hasn't already posted a review for the current state, preventing spam.
4. **AI Processing**: The diff is passed to the `gemini-2.5-flash-lite` model. The model processes the diff and returns a structured JSON response populated into our Pydantic schema.
5. **Publishing**: The structured JSON is formatted into a readable Markdown PR comment with an embedded hidden JSON block, and posted directly to the PR.
