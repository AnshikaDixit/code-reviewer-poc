def safe_divide(numerator, denominator):
    if denominator != 0:
        result = numerator / denominator
    else:
        result = 0.0
    return result