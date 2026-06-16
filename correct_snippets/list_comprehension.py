def test_process_scores(scores):
    # SyntaxError: invalid syntax
    cleaned_scores = [score if score > 0 for score in scores]
    return cleaned_scores