def generate_validators():
    funcs = []
    for i in range(3):
        def make_func(val=i):
            return val
        funcs.append(make_func)
    return funcs