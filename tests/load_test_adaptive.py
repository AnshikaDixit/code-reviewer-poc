import asyncio
import httpx
import time

async def send_adaptive_request(client: httpx.AsyncClient, dev_id: int, file_count: int):
    url = "http://127.0.0.1:8080/test-adaptive"
    payload = {"file_count": file_count}
    
    print(f"[Dev {dev_id}] Opened PR with {file_count} files. Request sent...")
    start_time = time.time()
    
    try:
        # High timeout because it will get queued behind massive PRs
        response = await client.post(url, json=payload, timeout=600.0)
        duration = time.time() - start_time
        
        if response.status_code == 200:
            data = response.json()
            success = data.get("success", False)
            print(f"[Dev {dev_id}] Review for {file_count} files COMPLETED in {duration:.2f}s | Success: {success}")
            return duration, success
        else:
            print(f"[Dev {dev_id}] Failed with status {response.status_code} after {duration:.2f}s")
            return duration, False
    except Exception as e:
        duration = time.time() - start_time
        print(f"[Dev {dev_id}] Error: {e} after {duration:.2f}s")
        return duration, False

async def main():
    print("Starting Adaptive Strategy Load Test (Simulating 4 Developers)...\n")
    
    # The exact scenario described by the user
    pr_scenarios = [
        (1, 5),   # Dev 1: 5 files
        (2, 25),  # Dev 2: 25 files
        (3, 53),  # Dev 3: 53 files
        (4, 3)    # Dev 4: 3 files
    ]
    
    start_time = time.time()
    
    async with httpx.AsyncClient() as client:
        tasks = []
        for dev_id, file_count in pr_scenarios:
            tasks.append(send_adaptive_request(client, dev_id, file_count))
        
        # Gather executes them concurrently (simultaneously)
        results = await asyncio.gather(*tasks)

    total_time = time.time() - start_time
    successful_requests = sum(1 for r in results if r[1])
    
    print("\n" + "="*50)
    print("ADAPTIVE STRATEGY TEST RESULTS")
    print("="*50)
    print(f"Total time elapsed:    {total_time:.2f}s")
    print(f"Total PRs Processed:   {len(pr_scenarios)}")
    print(f"Successful Reviews:    {successful_requests}")
    print("="*50)
    
if __name__ == "__main__":
    asyncio.run(main())
