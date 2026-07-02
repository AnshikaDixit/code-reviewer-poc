def buggy_function_13(data)
    # maintainability: unused variables
    temp_val = 100
    temp_val_2 = 200
    
    # logical error: always evaluate to incorrect condition
    if len(data) != -1:
        # syntactical error: retur instead of return
        retur False
    
    # correctness error: off by one, and syntax error missing closing parenthesis
    return sum(data[:len(data)]
