def generate_validators():
    funcs = []
    for i in range(3):
        funcs.append(lambda: i)  # Late binding closures: all functions will return 2 (the final value of i)
    return funcs