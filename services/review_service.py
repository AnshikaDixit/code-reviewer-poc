import time
from services.llm_service import LLMService
from services.github_service import GithubService
from services.patch_utils import calculate_local_risk_score, get_valid_lines, add_line_numbers_to_patch
from services.review_strategies import StrategyFactory

async def analyze_pull_request(repo_name: str, pr_number: int, commit_sha: str):
    """Main orchestration function for evaluating pull requests based on size."""
    print(f"Starting analysis for {repo_name} PR #{pr_number}")
    start_time = time.time()
    
    github_service = GithubService(repo_name)
    try:
        await github_service.get_installation_token()
    except Exception as e:
        print(f"Authentication failed: {e}")
        return

    llm_service = LLMService()

    try:
        # 1. Get already reviewed files to prevent duplicate reviews
        reviewed_files = set()
        existing_reviews = await github_service.get_existing_reviews(pr_number)
        
        for review in existing_reviews:
            body = review.get("body", "")
            if "### Ollama AI Review Feedback for `" in body:
                start_idx = body.find("### Ollama AI Review Feedback for `") + len("### Ollama AI Review Feedback for `")
                end_idx = body.find("`", start_idx)
                if end_idx != -1:
                    reviewed_files.add(body[start_idx:end_idx])

        # 2. Fetch the PR files
        pr_files = await github_service.get_pr_files(pr_number)
        if not pr_files:
            return

        eligible_files = []
        for file_obj in pr_files:
            filename = file_obj.get("filename", "")
            status = file_obj.get("status", "")
            patch = file_obj.get("patch", "")

            if not patch or status in ["removed", "unchanged"]:
                continue
            if filename.endswith((".lock", ".png", ".jpg", ".jpeg", ".svg", ".md", ".json")):
                continue
            if filename in reviewed_files:
                print(f"Skipping {filename}: Review already exists.")
                continue

            eligible_files.append(file_obj)

        if not eligible_files:
            print("No eligible files found to review.")
            return

        for f in eligible_files:
            f['local_score'] = calculate_local_risk_score(f.get('filename', ''), f.get('patch', ''))
            f['valid_lines'] = get_valid_lines(f.get('patch', ''))
            f['numbered_patch'] = add_line_numbers_to_patch(f.get('patch', ''))

        file_count = len(eligible_files)
        print(f"Total eligible files: {file_count}")

        # 3. Apply adaptive strategy logic
        strategy = StrategyFactory.get_strategy(file_count, llm_service, github_service, commit_sha)
        await strategy.execute(eligible_files, pr_number)

    except Exception as e:
        print(f"Exception during PR analysis: {e}")