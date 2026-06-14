def test_process_scores(scores):
# Using a list comprehension strictly for its side effects (bad practice)
    [print(score) for score in scores if score > 0]