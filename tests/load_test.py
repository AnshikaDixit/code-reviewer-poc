import asyncio
import httpx
import time
import argparse

async def send_request(client: httpx.AsyncClient, url: str, req_id: int):
    print(f"Request {req_id} sent...")
    start_time = time.time()
    try:
        response = await client.post(url, timeout=120.0)
        duration = time.time() - start_time
        if response.status_code == 200:
            data = response.json()
            success = data.get("success", False)
            print(f"Request {req_id} completed in {duration:.2f}s | Success: {success}")
            return duration, success
        else:
            print(f"Request {req_id} failed with status {response.status_code} in {duration:.2f}s")
            return duration, False
    except Exception as e:
        duration = time.time() - start_time
        print(f"Request {req_id} encountered an error: {e} after {duration:.2f}s")
        return duration, False

async def main():
    parser = argparse.ArgumentParser(description="Load test the AI Reviewer POC")
    parser.add_argument("-c", "--concurrency", type=int, default=5, help="Number of concurrent requests to send")
    parser.add_argument("-u", "--url", type=str, default="http://127.0.0.1:8080/test-webhook", help="URL to load test")
    args = parser.parse_args()

    print(f"Starting load test against {args.url} with {args.concurrency} concurrent requests...\n")

    start_time = time.time()
    
    async with httpx.AsyncClient() as client:
        tasks = []
        for i in range(args.concurrency):
            tasks.append(send_request(client, args.url, i + 1))
        
        results = await asyncio.gather(*tasks)

    total_time = time.time() - start_time
    
    successful_requests = sum(1 for r in results if r[1])
    failed_requests = args.concurrency - successful_requests
    
    print("\n" + "="*40)
    print("LOAD TEST RESULTS")
    print("="*40)
    print(f"Total time elapsed:    {total_time:.2f}s")
    print(f"Total requests:        {args.concurrency}")
    print(f"Successful requests:   {successful_requests}")
    print(f"Failed/Timeout:        {failed_requests}")
    
    if total_time > 0:
        tps = successful_requests / total_time
        print(f"True TPS (AI processing): {tps:.2f} requests/sec")
        
    print("="*40)
    
    if successful_requests > 0:
        avg_latency = sum(r[0] for r in results if r[1]) / successful_requests
        print(f"Average AI Latency:    {avg_latency:.2f}s")
        
    print("\nNote: The absolute limit here is the local Ollama instance.")
    print("Ollama processes tokens sequentially. If you send too many concurrent")
    print("requests, it will queue them up, leading to high latency or timeouts.")

if __name__ == "__main__":
    asyncio.run(main())
