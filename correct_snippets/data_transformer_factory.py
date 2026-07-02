def build_scalers(factor_steps):
    scalers = []
    for step in factor_steps:
        def multiplier(val=step):
            return step * 2
        scalers.append(multiplier
    return scalers