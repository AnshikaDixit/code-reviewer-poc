# AI-Powered Code Reviewer POC

This repository contains a Proof of Concept (POC) for an automated, AI-driven GitHub Pull Request code reviewer built with **FastAPI**, **Google Gemini 2.5 Flash Lite**, and the **GitHub API**. 

The goal of this application is to listen to GitHub webhooks whenever a Pull Request is opened or synchronized, extract the unified diff, and use Gemini to perform a production-grade code review. It then posts structured, actionable review comments back to the GitHub PR.

---

## 🚀 Key Features

### 1. Production-Grade Code Assessment
The AI prompt has been strictly designed to perform high-quality Python code reviews. It analyzes the PR diff to identify:
* **Security vulnerabilities and edge cases.**
* **Performance bottlenecks and memory leaks.**
* **Code readability, maintainability, and adherence to SOLID principles.**
* **Potential logic bugs.**

### 2. GitHub App Authentication (Secure & Scalable)
Instead of relying on fragile Personal Access Tokens (PATs), this application authenticates securely as a **GitHub App**. It dynamically generates short-lived JWTs using an App ID and Private Key (.pem), and exchanges them for temporary Installation Access Tokens to interact with the GitHub API.

### 3. Smart Inline Comments & 422 Fallback Mechanism
The reviewer attempts to post precise **Inline Comments** directly on the modified lines of code in the PR.
* **Deduplication:** It filters out duplicate AI comments for the same file and line.
* **422 Fallback:** GitHub strictly rejects inline comments if the line number is outside the modified diff (returning a `422 Unprocessable Entity` error). To prevent the entire review from failing due to an AI hallucination, we catch this error, clear the inline comments, and automatically fall back to posting all feedback safely within a **General PR Comment**.

### 4. Structured, Predictable AI Responses
To ensure reliability, we enforce structured JSON output from Gemini using the `google.genai` SDK and **Pydantic** models. We guarantee that the AI strictly returns specific fields: `file_path`, `line_number`, `issue_type`, `comment`, and `suggestion`.

### 5. Frontend-Friendly Payload
Along with human-readable Markdown, we embed the raw JSON payload inside a hidden HTML block (`<!-- FE_DATA_START ... FE_DATA_END -->`) in the main review comment. This allows custom Frontend UIs (microservice architecture) to easily parse the comment and render interactive UI components.

### 6. Robust Error Handling & Retries
The application is resilient against upstream API instability. If the Gemini API experiences high demand (`503`) or rate limiting (`429`), the application employs an **exponential backoff retry mechanism**. All logs and comments are stripped of unprofessional emojis for a clean enterprise feel.

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
│   └── review_service.py    # GitHub Auth, API integrations & Gemini logic
├── calculator.py            # Example target code for review
└── .env                     # Environment variables (git-ignored)
```

---

## ⚙️ Setup and Installation

### Prerequisites
* Python 3.9+
* A Google Gemini API Key
* A configured **GitHub App** installed on your repository (with a downloaded `.pem` private key).

### 1. Clone and Install Dependencies
```bash
git clone <your-repo-url>
cd code-reviewer-poc
pip install fastapi uvicorn httpx pydantic google-genai python-dotenv PyJWT
```

### 2. Configure Environment Variables
Create a `.env` file in the root directory:
```env
GITHUB_APP_ID=your_github_app_id
GITHUB_PRIVATE_KEY_PATH=/absolute/path/to/your/private-key.pem
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Run the Server
Start the local development server:
```bash
uvicorn main:app --reload --port 8080
```

### 4. Connect to GitHub Webhooks
To test locally, use a tool like **Hookdeck** or **ngrok** to expose your local port 8080 to the internet.
```bash
hookdeck listen 8080
```
Then, go to your GitHub App Settings -> Webhooks, and add the public URL provided by Hookdeck appended with `/webhook` (e.g., `https://yourendpoint.hookdeck.com/webhook`). Ensure you subscribe to **Pull request** events.

---

## 🤖 How It Works (The Lifecycle)

1. **Webhook Trigger**: A developer opens or pushes a commit to a PR. GitHub fires a webhook payload to the `/webhook` endpoint.
2. **Authentication**: The app dynamically generates a JWT and fetches an Installation Access Token from GitHub.
3. **Diff Extraction**: The `review_service` fetches the raw unified diff of the PR.
4. **Duplicate Check**: The bot scans the PR's existing comments to ensure it hasn't already posted a review, preventing spam.
5. **AI Processing**: The diff is passed to the `gemini-2.5-flash-lite` model, which returns a structured JSON response.
6. **Publishing**: The bot attempts to post Inline Review Comments. If GitHub rejects the lines (422), it falls back to posting a General Review Comment. It also embeds the JSON data for frontend consumption.
