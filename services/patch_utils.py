import re

def get_valid_lines(patch: str) -> set:
    valid_lines = set()
    if not patch:
        return valid_lines
    lines = patch.split('\n')
    current_line = 0
    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for line in lines:
        match = hunk_header_re.match(line)
        if match:
            current_line = int(match.group(1))
        elif line.startswith('+') or line.startswith(' '):
            valid_lines.add(current_line)
            current_line += 1

    return valid_lines

def add_line_numbers_to_patch(patch: str) -> str:
    if not patch:
        return ""
    lines = patch.split('\n')
    result = []
    current_line = 0
    hunk_header_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

    for line in lines:
        match = hunk_header_re.match(line)
        if match:
            current_line = int(match.group(1))
            result.append(line)
        elif line.startswith('+') or line.startswith(' '):
            result.append(f"{current_line}: {line}")
            current_line += 1
        elif line.startswith('-'):
            result.append(f"    {line}")
        else:
            result.append(line)

    return '\n'.join(result)

def calculate_local_risk_score(filename: str, patch: str) -> float:
    if any(x in filename.lower() for x in ['generated', 'migrations/', 'alembic/versions/', 'package-lock.json', 'yarn.lock']):
        return 0.0

    base_score = 1.0
    if patch:
        base_score += sum(1 for line in patch.split('\n') if line.startswith('+') and not line.startswith('+++'))

    if any(x in filename.lower() for x in ['auth/', 'payment/', 'crypto/', 'security/']):
        base_score *= 3.0

    if any(x in filename.lower() for x in ['test', 'tests/', 'spec.py']):
        base_score *= 0.5

    return base_score
