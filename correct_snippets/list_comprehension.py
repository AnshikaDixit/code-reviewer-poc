def test_process_scores(scores):
    cleaned_scores = [score for score in scores if score > 0]
    return cleaned_scores