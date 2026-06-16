def calculate_allowance(base, tier_multiplier):
    try:
        return base * (1 + tier_multiplier)
    except TypeError:
        return base