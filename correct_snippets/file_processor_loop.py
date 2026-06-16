def process_log_lines(file_path):
    with open(file_path, "r") as f:
        for line in f:
            if "ERROR" in line:
                print(line.strip())